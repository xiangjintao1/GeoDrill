# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""对照原始链路与优化链路，记录耗时、模型次数及同题验收结果。"""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from evaluate import grade
from service import DEFAULT_CONFIG, ROOT, answer
import run as cli


def summarize(rows):
    summary = {}
    for strategy in ["baseline", "optimized"]:
        group = [r for r in rows if r["strategy"] == strategy]
        times = sorted(r["duration_seconds"] for r in group if not r.get("error"))
        calls = [r["performance"]["model_calls"] for r in group if not r.get("error")]
        summary[strategy] = {"samples": len(group), "errors": len(group) - len(times),
            "rule_pass_rate": sum(bool(r.get("rule_pass")) for r in group) / len(group) if group else None,
            "mean_seconds": round(statistics.mean(times), 3) if times else None,
            "p50_seconds": statistics.median(times) if times else None,
            "p95_seconds": times[math.ceil(len(times) * .95) - 1] if times else None,
            "mean_model_calls": round(statistics.mean(calls), 2) if calls else None}
    return summary


async def benchmark(cases, repeats, config_path, destination):
    config = cli.load_config(config_path)
    manifests = [ROOT / "corpus/sources.json", ROOT / "corpus/foundation-sources.json"]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "repeats": repeats,
        "config": {"model": config["openie_llm"]["model"], "embedding": config["vectorize_model"]["model"],
                   "namespace": config["project"]["namespace"]},
        "cases_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        "sources_sha256": hashlib.sha256(b"".join(p.read_bytes() for p in manifests)).hexdigest(),
        "rows": [], "note": "每轮按整组轮换策略次序；首次包含启动，后续可复用运行实例。不缓存答案；规则验收不代表语义准确率，小样本不构成稳定延迟保证。"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    for repeat in range(repeats):
        strategies = ["baseline", "optimized"] if repeat % 2 == 0 else ["optimized", "baseline"]
        for strategy in strategies:
            for case in cases:
                print(f"{repeat+1}/{repeats} {strategy} {case['id']}", flush=True)
                row = {"id": case["id"], "strategy": strategy, "repeat": repeat + 1}
                try:
                    result = await answer(case["question"], strategy=strategy, config_path=config_path)
                    row.update(result)
                    row.update(grade(case, result))
                except Exception as error:
                    row["error"] = type(error).__name__
                report["rows"].append(row)
                report["summary"] = summarize(report["rows"])
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--case-ids", nargs="+", default=["coring-principle", "bit-diameter", "missing-standard"])
    parser.add_argument("--output", type=Path, default=ROOT / "results/performance/latest.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats 必须为正整数")
    all_cases = json.loads((ROOT / "benchmark.json").read_text(encoding="utf-8"))
    if set(args.case_ids) - {x["id"] for x in all_cases}:
        parser.error("存在未知的 case-id")
    cases = [x for x in all_cases if x["id"] in args.case_ids]
    report = asyncio.run(benchmark(cases, args.repeats, args.config.resolve(), args.output.resolve()))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return int(any(row.get("error") for row in report["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
