# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""问答工作台与评测共用的业务逻辑，不依赖 Web 框架。"""

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import run as cli

ROOT = cli.PROJECT_DIR
DEFAULT_CONFIG = ROOT / "kag_config.local.yaml"
CITATION = re.compile(r'<reference\s+id=["\']([^"\']+)["\']\s*>\s*</reference>')


def clean_text(value):
    value = str(value or "")
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1].replace("\\n", "\n")
    return value


def references(result):
    items = []
    for index, item in enumerate(result.get("trace", {}).get("reference", [])):
        content = clean_text(item.get("content"))
        urls = re.findall(r'https?://[^\s<>"\\]+', content)
        items.append({
            "id": f"chunk:0_{index}", "title": clean_text(item.get("title")),
            "content": content, "chunk_id": item.get("chunk_id", ""),
            "urls": list(dict.fromkeys(urls)),
        })
    return items


def retrieval_config(config, mode):
    if mode not in {"hybrid", "vector"}:
        raise ValueError("不支持的检索方式")
    config = copy.deepcopy(config)
    if mode == "vector":
        executor = config["kag_solver_pipeline"]["executors"][0]
        executor["retrievers"] = [r for r in executor["retrievers"] if r["type"] == "rc_open_spg"]
        if not executor["retrievers"]:
            raise ValueError("配置中缺少文本向量检索器")
    return config


async def answer(question, mode="hybrid", config_path=DEFAULT_CONFIG):
    question = question.strip()
    if not 1 <= len(question) <= 800:
        raise ValueError("请输入1—800字的问题")
    config = retrieval_config(cli.load_config(Path(config_path)), mode)
    cli.validate_config(config)
    cli.init_runtime(config)
    started = time.perf_counter()
    result = await cli.ask(config, question, emit=False)
    if result["status"] != "FINISH":
        raise RuntimeError("问答流水线未正常完成")
    refs = references(result)
    used = list(dict.fromkeys(CITATION.findall(result["answer"])))
    known = {r["id"] for r in refs}
    result.update({
        "mode": mode, "duration_seconds": round(time.perf_counter() - started, 2),
        "references": refs, "used_citations": used,
        "invalid_citations": [key for key in used if key not in known],
    })
    return result


def catalog():
    """只暴露清单中的语料，不接受任意文件路径。"""
    records = []
    manifests = [ROOT / "corpus/sources.json", ROOT / "corpus/foundation-sources.json"]
    for path in manifests:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data["knowledge_cards"] + data["reference_chunks"]
        for row in rows:
            file = (ROOT / "corpus" / row["file"]).resolve()
            if not file.is_relative_to((ROOT / "corpus").resolve()) or not file.is_file():
                continue
            text = file.read_text(encoding="utf-8")
            url = row["source_url"]
            if urlparse(url).scheme not in {"http", "https"}:
                url = ""
            records.append({
                "id": hashlib.sha256(row["file"].encode()).hexdigest()[:16],
                "title": text.splitlines()[0].removeprefix("# "), "file": row["file"],
                "kind": row.get("format", "英文手册原文"), "url": url, "content": text,
                "page": row.get("printed_page", row.get("printed_pages", "")),
            })
    return records
