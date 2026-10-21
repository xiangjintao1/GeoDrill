# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""通过真实 HTTP 接口验收观测提取，不自动将模型草稿送入诊断。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from diagnosis import KNOWLEDGE

ROOT = Path(__file__).resolve().parent


def grade(case, result):
    expected = {field: case["expected"].get(field, "unknown") for field in KNOWLEDGE["observations"]}
    actual = result.get("observations", {})
    failures = [field for field, value in expected.items() if actual.get(field) != value]
    if set(actual) != set(expected) or result.get("status") != "FINISH" or result.get("review_required") is not True:
        failures.append("response_contract")
    for evidence in result.get("evidence", []):
        if not evidence.get("quotes") or any(quote not in case["text"] for quote in evidence["quotes"]):
            failures.append("evidence_quote")
    for field, value in actual.items():
        if value != "unknown" and not any(item["field"] == field and item["value"] == value for item in result.get("evidence", [])):
            failures.append("missing_evidence:" + field)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8090")
    parser.add_argument("--limit", type=int, default=8, choices=range(1, 9))
    parser.add_argument("--output", type=Path, default=ROOT / "results/extraction/latest.json")
    args = parser.parse_args()
    suite = json.loads((ROOT / "diagnosis/extraction-benchmark.json").read_text(encoding="utf-8"))
    rows = []
    with requests.Session() as session:
        for case in suite["cases"][:args.limit]:
            try:
                response = session.post(args.url.rstrip("/") + "/api/diagnosis/extract",
                                        json={"text": case["text"]}, timeout=180)
                response.raise_for_status()
                result = response.json()
                row = {"id": case["id"], "failures": grade(case, result), "result": result}
            except Exception as error:
                row = {"id": case["id"], "failures": [type(error).__name__]}
            rows.append(row)
            print(case["id"], "PASS" if not row["failures"] else "FAIL " + ",".join(row["failures"]), flush=True)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "scope": suite["scope"],
              "passed": sum(not row["failures"] for row in rows), "samples": len(rows), "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['samples']} extraction checks passed")
    raise SystemExit(0 if report["passed"] == report["samples"] else 1)


if __name__ == "__main__":
    main()
