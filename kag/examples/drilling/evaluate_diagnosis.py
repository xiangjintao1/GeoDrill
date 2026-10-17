# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""通过真实HTTP接口复测诊断逻辑；不把回归通过率称为根因准确率。"""

import argparse
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent


def grade(case, result):
    candidates = {item["id"]: item for item in result["candidates"]}
    failures = [key for key, expected in case["expected"].items()
                if candidates.get(key, {}).get("status") != expected]
    asked = {item["field"] for item in result["follow_up"]}
    failures += ["follow_up:" + field for field in case.get("follow_up", []) if field not in asked]
    if case.get("path") and not any(item["inference_path"] == case["path"] for item in candidates.values()):
        failures.append("inference_path")
    if result.get("status") != "FINISH" or "author_analysis" in json.dumps(result):
        failures.append("response_contract")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8090")
    parser.add_argument("--output", type=Path, default=ROOT / "results/diagnosis/latest.json")
    args = parser.parse_args()
    suite = json.loads((ROOT / "diagnosis/benchmark.json").read_text(encoding="utf-8"))
    rows = []
    with requests.Session() as session:
        for case in suite["cases"]:
            try:
                response = session.post(args.url.rstrip("/") + "/api/diagnose",
                    json={"observations": case["observations"]}, timeout=60)
                response.raise_for_status()
                result = response.json()
                row = {"id": case["id"], "failures": grade(case, result), "result": result}
            except Exception as error:
                row = {"id": case["id"], "failures": [type(error).__name__]}
            rows.append(row)
            print(case["id"], "PASS" if not row["failures"] else "FAIL", flush=True)
    report = {"scope": suite["scope"], "passed": sum(not row["failures"] for row in rows),
              "samples": len(rows), "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['samples']} logic checks passed")
    raise SystemExit(0 if report["passed"] == report["samples"] else 1)


if __name__ == "__main__":
    main()
