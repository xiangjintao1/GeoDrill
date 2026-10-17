# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""离线验证 OAuth 权限和流式响应；不调用真实模型。"""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace as Event
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drilling_auth", ROOT / "chatgpt_auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


class ChatGPTProtocolTests(unittest.TestCase):
    def test_token_without_plan_permission_is_rejected(self):
        response = Event(ok=True, json=lambda: {"scope": "openid email", "access_token": "secret"})
        with patch.object(auth.requests, "post", return_value=response):
            with self.assertRaises(ValueError) as error:
                auth.exchange({"grant_type": "authorization_code"})
        self.assertNotIn("secret", str(error.exception))

    def test_exchange_failure_does_not_include_response_body(self):
        response = Event(ok=False, status_code=400, text="secret-token")
        with patch.object(auth.requests, "post", return_value=response):
            with self.assertRaises(ValueError) as error:
                auth.exchange({})
        self.assertNotIn("secret-token", str(error.exception))

    def test_dpapi_roundtrip(self):
        if auth.os.name != "nt":
            self.skipTest("Windows DPAPI")
        encrypted = auth.protect(b"test-credential")
        self.assertNotIn(b"test-credential", encrypted)
        self.assertEqual(auth.protect(encrypted, decrypt=True), b"test-credential")

    def test_stream_requires_terminal_success(self):
        from kag.examples.drilling.chatgpt_client import collect_response

        delta = Event(type="response.output_text.delta", delta="partial")
        for events in ([delta], [delta, Event(type="response.failed")],
                       [delta, Event(type="response.incomplete")]):
            with self.assertRaises(ValueError):
                collect_response(events)
        text, _ = collect_response([delta, Event(type="response.completed", response=Event(usage=None))])
        self.assertEqual(text, "partial")

    def test_system_message_becomes_developer_and_input_is_array(self):
        from kag.examples.drilling.chatgpt_client import response_input

        self.assertEqual(response_input("hello"), [{"role": "user", "content": "hello"}])
        self.assertEqual(response_input([{"role": "system", "content": "rules"}])[0]["role"], "developer")
        with self.assertRaises(ValueError):
            response_input([])


if __name__ == "__main__":
    unittest.main()
