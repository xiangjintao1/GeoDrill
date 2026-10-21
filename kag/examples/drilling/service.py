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
_configuration = None
_pipelines = {}


def initialize_runtime(config, effective=None, reuse=True):
    """每个隔离查询进程复用同一套配置；配置变化时丢弃业务实例。"""
    global _configuration
    signature = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if reuse and _configuration == signature:
        return True
    _pipelines.clear()
    _configuration = None
    cli.init_runtime(effective if effective is not None else config)
    if reuse:
        _configuration = signature
    return False


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


async def answer(question, mode="hybrid", config_path=DEFAULT_CONFIG, strategy="optimized", on_event=None):
    # 每个查询进程同一时刻只处理一个请求，缓存和全局 KAG 配置不跨进程共享。
    question = question.strip()
    if not 1 <= len(question) <= 800:
        raise ValueError("请输入1—800字的问题")
    started = time.perf_counter()
    if strategy not in {"baseline", "optimized"}:
        raise ValueError("不支持的问答策略")
    base = cli.load_config(Path(config_path))
    config = retrieval_config(base, mode)
    cli.validate_config(config)
    reused = initialize_runtime(base, config, reuse=strategy == "optimized")
    from kag.examples.drilling.telemetry import CURRENT, QueryMetrics

    metrics = QueryMetrics(strategy, on_event)
    metrics.started = started
    metrics.spans.append({"name": "initialization", "seconds": round(time.perf_counter() - started, 3)})
    config["kag_solver_pipeline"]["type"] = "drilling_profiled_pipeline"
    config["kag_solver_pipeline"]["executors"][0]["type"] = "drilling_profiled_retriever"
    if strategy == "optimized":
        config["kag_solver_pipeline"]["planner"]["plan_prompt"]["type"] = "drilling_fast_planning"
    token = CURRENT.set(metrics)
    try:
        pipeline = None
        if strategy == "optimized":
            if mode not in _pipelines:
                _pipelines[mode] = cli.create_pipeline(config)
            pipeline = _pipelines[mode]
        result = await cli.ask(config, question, emit=False, pipeline=pipeline)
    finally:
        CURRENT.reset(token)
    if result["status"] != "FINISH":
        raise RuntimeError("问答流水线未正常完成")
    refs = references(result)
    used = list(dict.fromkeys(CITATION.findall(result["answer"])))
    known = {r["id"] for r in refs}
    result.update({
        "mode": mode, "duration_seconds": round(time.perf_counter() - started, 2),
        "references": refs, "used_citations": used,
        "invalid_citations": [key for key in used if key not in known],
        "strategy": strategy, "runtime_reused": reused, "performance": metrics.summary(),
    })
    return result


async def diagnose(case, config_path=DEFAULT_CONFIG, on_event=None):
    """独立的 KAG 诊断扩展，不走简单问答快捷路径，也不让模型补齐未知观测。"""
    from diagnosis import DiagnosisCase, KNOWLEDGE_HASH
    from kag.examples.drilling.telemetry import CURRENT, QueryMetrics

    case = DiagnosisCase.model_validate(case)
    config = cli.load_config(Path(config_path))
    cli.validate_config(config)
    metrics = QueryMetrics("diagnosis", on_event)
    metrics.route = "diagnosis"
    token = CURRENT.set(metrics)
    try:
        reused = initialize_runtime(config)
        if "diagnosis" not in _pipelines:
            from kag.interface import SolverPipelineABC
            _pipelines["diagnosis"] = SolverPipelineABC.from_config({
                "type": "drilling_diagnosis_pipeline",
                "graph": {"type": "drilling_diagnosis_graph", "host_addr": config["project"]["host_addr"],
                          "project_id": config["project"]["id"]},
                "reasoning": {"type": "drilling_diagnosis_rules"},
                "case_comparison": {"type": "drilling_diagnosis_cases"}})
        result = await _pipelines["diagnosis"].ainvoke(case.model_dump())
    finally:
        CURRENT.reset(token)
    return {**result, "knowledge_hash": KNOWLEDGE_HASH, "status": "FINISH", "runtime_reused": reused,
            "performance": metrics.summary(), "duration_seconds": round(time.perf_counter() - metrics.started, 3)}


async def extract_observations(body, config_path=DEFAULT_CONFIG, on_event=None):
    """只生成待核对草稿，不读写图谱，不自动调用诊断。"""
    from diagnosis_extract import NarrativeInput, messages, parse_proposals
    from kag.interface import LLMClient
    from kag.examples.drilling.telemetry import CURRENT, QueryMetrics, stage

    body = NarrativeInput.model_validate(body)
    config = cli.load_config(Path(config_path))
    cli.validate_config(config)
    metrics = QueryMetrics("extraction", on_event)
    metrics.route = "extraction"
    token = CURRENT.set(metrics)
    try:
        reused = initialize_runtime(config)
        if "observation_extractor" not in _pipelines:
            _pipelines["observation_extractor"] = LLMClient.from_config(config["chat_llm"])
        with stage("diagnosis.extraction"):
            raw = await _pipelines["observation_extractor"].acall(
                messages=messages(body.text), segment_name="diagnosis_extraction")
            result = parse_proposals(raw, body.text)
    finally:
        CURRENT.reset(token)
    return {**result, "status": "FINISH", "runtime_reused": reused,
            "performance": metrics.summary(), "duration_seconds": round(time.perf_counter() - metrics.started, 3)}


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
