# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""同题比较检索方式；规则检查与语义正确性分开报告。"""

import argparse
import asyncio
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from service import DEFAULT_CONFIG, ROOT, answer
import run as cli


def grade(case, result):
    text = result["answer"].casefold()
    facts = all(any(word.casefold() in text for word in group) for group in case["facts"])
    facts = facts and not any(word.casefold() in text for word in case.get("forbidden", []))
    sources = "\n".join(r["title"] + "\n" + r["content"] for r in result["references"])
    source_hit = any(value in sources for value in case["source_any"])
    valid = bool(result["used_citations"]) and not result["invalid_citations"]
    return {"fact_rules_pass": facts, "source_recalled": source_hit, "citation_ids_valid": valid,
            "rule_pass": facts and source_hit and valid}


def summarize(rows):
    groups = {}
    for mode in sorted({r["mode"] for r in rows}):
        group = [r for r in rows if r["mode"] == mode]
        successful = [r for r in group if not r.get("error")]
        times = sorted(r["duration_seconds"] for r in successful)
        missing = [r for r in group if r.get("unanswerable")]
        def rate(key, items=group):
            return round(sum(bool(r.get(key)) for r in items) / len(items), 3) if items else None
        groups[mode] = {
            "samples": len(group), "errors": len(group) - len(successful),
            "fact_rule_rate": rate("fact_rules_pass"), "source_recall_rate": rate("source_recalled"),
            "citation_id_valid_rate": rate("citation_ids_valid"), "rule_pass_rate": rate("rule_pass"),
            "unanswerable_rule_rate": rate("fact_rules_pass", missing),
            "mean_seconds": round(statistics.mean(times), 2) if times else None,
            "p95_seconds": times[max(0, (95 * len(times) + 99) // 100 - 1)] if times else None,
        }
    return groups


async def evaluate(cases, modes, config_path):
    rows = []
    for index, case in enumerate(cases):
        # 轮换两种模式的先后，减少固定调用顺序的影响。
        for mode in modes if index % 2 == 0 else list(reversed(modes)):
            print(f"[{len(rows)+1}/{len(cases)*len(modes)}] {case['id']} / {mode}", flush=True)
            row = {"id": case["id"], "question": case["question"], "mode": mode,
                   "kind": case["kind"], "unanswerable": case.get("unanswerable", False)}
            try:
                result = await answer(case["question"], mode, config_path)
                row.update(grade(case, result))
                row.update({key: result[key] for key in (
                    "answer", "duration_seconds", "references", "used_citations", "invalid_citations")})
            except Exception as error:
                # 原始异常可能含配置或请求内容；公开报告仅记录异常类型。
                row["error"] = type(error).__name__
            rows.append(row)
    config = cli.load_config(config_path)
    fingerprint = {"model": config["openie_llm"]["model"], "embedding": config["vectorize_model"]["model"],
                   "dimensions": config["vectorize_model"]["vector_dimensions"], "namespace": config["project"]["namespace"]}
    return {"created_at": datetime.now(timezone.utc).isoformat(), "question_count": len(cases),
            "benchmark_sha256": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "config": fingerprint, "summary": summarize(rows), "rows": rows,
            "note": "自动规则用于检查预期事实、来源召回和引用编号；不等于语义正确率或引用支持率，需人工复核。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmark.json")
    parser.add_argument("--mode", choices=["both", "hybrid", "vector"], default="both")
    parser.add_argument("--limit", type=int, help="只运行前N题，用于连通性验证")
    parser.add_argument("--output", type=Path, default=ROOT / "results/evaluation/latest.json")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("limit必须为正整数")
    cases = json.loads(args.cases.resolve().read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        parser.error("评测集不能为空")
    destination = args.output.resolve()
    report = asyncio.run(evaluate(cases, ["hybrid", "vector"] if args.mode == "both" else [args.mode],
                                  args.config.resolve()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告已保存：{destination}")
    return int(any(row.get("error") for row in report["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
