# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""ChatGPT 官方 OAuth 登录；凭据保存在当前 Windows 用户的加密存储中。"""

import argparse
import base64
import ctypes
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTH = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
STORE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GeoDrill" / "chatgpt"
LOCK = threading.Lock()


def protect(data, decrypt=False):
    """Windows DPAPI：只有当前系统用户能解密，不保存明文 Token。"""
    if os.name != "nt":
        raise OSError("当前凭据存储仅支持 Windows DPAPI")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    operation = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Windows 凭据加密/解密失败")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def read_record():
    path = STORE / "account.dat"
    return json.loads(protect(path.read_bytes(), decrypt=True)) if path.exists() else {}


def save_record(record):
    STORE.mkdir(parents=True, exist_ok=True)
    temporary = STORE / "account.tmp"
    temporary.write_bytes(protect(json.dumps(record).encode("utf-8")))
    temporary.replace(STORE / "account.dat")


def exchange(fields):
    response = requests.post(AUTH + "/api/accounts/oauth/token", data={
        **fields, "resource": RESOURCE,
    }, timeout=30)
    if not response.ok:
        # 不输出响应正文，避免授权码或 Token 出现在日志里。
        raise ValueError(f"授权交换失败（HTTP {response.status_code}），请重新登录")
    token = response.json()
    if "chatgpt.tokens.use.direct" not in token.get("scope", "").split():
        raise ValueError("尚未授予 ChatGPT 套餐调用权限，请重新登录并检查授权页面")
    if not token.get("access_token") or str(token.get("token_type", "")).lower() != "bearer":
        raise ValueError("授权服务返回了无效凭据")
    return {**token, "expires_at": time.time() + int(token["expires_in"])}


def validate_identity(token, client_id, nonce):
    import jwt

    try:
        key = jwt.PyJWKClient(AUTH + "/.well-known/jwks.json").get_signing_key_from_jwt(token)
        identity = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                              issuer=AUTH, options={"require": ["exp", "iss", "aud", "sub", "nonce"]})
    except jwt.PyJWTError:
        raise ValueError("登录身份签名或有效期校验失败，请重新登录") from None
    if not secrets.compare_digest(str(identity["nonce"]), nonce):
        raise ValueError("登录身份校验失败：nonce 不匹配")
    return identity


def access_token():
    with LOCK:
        record = read_record()
        if not record.get("access_token"):
            raise ValueError("请先运行 chatgpt_auth.py login 完成登录")
        if record["expires_at"] <= time.time() + 30:
            fresh = exchange({"grant_type": "refresh_token", "client_id": record["client_id"],
                              "refresh_token": record["refresh_token"]})
            record.update(fresh)
            save_record(record)
        return record["access_token"]


def list_models():
    response = requests.get(RESOURCE + "/models", headers={
        "Authorization": "Bearer " + access_token(),
    }, timeout=30)
    if not response.ok:
        raise ValueError(f"读取模型列表失败（HTTP {response.status_code}）")
    models = [m for m in response.json().get("models", []) if m.get("visibility") == "list"]
    for model in models:
        print(f"{model['slug']}  {model.get('display_name', '')}")
    return models


def login(timeout=600):
    previous = read_record()
    # 每次显式登录可以选择账号；不读取其他应用或 Codex 的凭据。
    host_id = previous.get("ext_agent_host_id", "urn:uuid:" + str(uuid.uuid4()))
    save_record({**previous, "ext_agent_host_id": host_id})
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            valid = parsed.path == "/auth/callback" and secrets.compare_digest(values.get("state", [""])[0], state)
            if valid:
                result.update({k: v[0] for k, v in values.items()})
            body = b"Authorization received. You may return to GeoDrill." if valid else b"Invalid callback."
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        requested_client = previous.get("client_id", "dynamic_agent_client")
        registration = {"agent_name_hint": "GeoDrill Drilling"} if requested_client == "dynamic_agent_client" else {}
        url = AUTH + "/api/accounts/authorize?" + urlencode({
            "client_id": requested_client, **registration,
            "ext_agent_host_id": host_id, "response_type": "code", "redirect_uri": redirect,
            "scope": SCOPES, "resource": RESOURCE, "state": state, "nonce": nonce,
            "code_challenge_method": "S256", "code_challenge": challenge,
        })
        print("请在打开的官方页面点击 Continue with ChatGPT，登录并检查套餐授权。", flush=True)
        print("若浏览器未打开，可复制本次登录地址：\n" + url, flush=True)
        webbrowser.open(url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result:
        raise ValueError("登录等待超时，请重新运行 login")
    if result.get("error"):
        raise ValueError("登录未完成或用户取消了授权")
    client_id = result.get("client_id", "" if requested_client == "dynamic_agent_client" else requested_client)
    if requested_client != "dynamic_agent_client" and client_id != requested_client:
        raise ValueError("返回的客户端 ID 与本次登录不一致")
    if not client_id or client_id == "dynamic_agent_client" or not result.get("code"):
        raise ValueError("注册未返回有效的客户端 ID 或授权码")
    token = exchange({"grant_type": "authorization_code", "client_id": client_id,
                      "code": result["code"], "code_verifier": verifier, "redirect_uri": redirect})
    identity = validate_identity(token["id_token"], client_id, nonce)
    if previous.get("subject") and identity["sub"] != previous["subject"]:
        raise ValueError("登录账号与已保存账号不同，请先 logout 再添加新账号")
    save_record({**token, "client_id": client_id, "ext_agent_host_id": host_id,
                 "subject": identity["sub"]})
    print("登录成功，凭据已用 Windows DPAPI 加密保存。", flush=True)
    list_models()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["login", "models", "logout"])
    args = parser.parse_args()
    try:
        if args.command == "login":
            login()
        elif args.command == "models":
            list_models()
        else:
            previous = read_record()
            save_record({"ext_agent_host_id": previous.get("ext_agent_host_id", "urn:uuid:" + str(uuid.uuid4()))})
            print("本地登录凭据已清除；远程授权可在 ChatGPT 的连接管理中撤销。")
    except (ValueError, OSError, requests.RequestException) as error:
        print(f"操作失败：{error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
