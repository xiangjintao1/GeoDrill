# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""检索隔离、引用追踪、评测边界和 HTTP 输入验证。"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
import evaluate
import web
from fastapi.testclient import TestClient


class WorkbenchTests(unittest.TestCase):
    def test_vector_mode_keeps_original_hybrid_config(self):
        config = {"kag_solver_pipeline": {"executors": [{"retrievers": [
            {"type": "kg_cs_open_spg"}, {"type": "rc_open_spg"}]}]}}
        vector = service.retrieval_config(config, "vector")
        self.assertEqual(len(config["kag_solver_pipeline"]["executors"][0]["retrievers"]), 2)
        self.assertEqual(vector["kag_solver_pipeline"]["executors"][0]["retrievers"],
                         [{"type": "rc_open_spg"}])
        with self.assertRaises(ValueError):
            service.retrieval_config(config, "unknown")

    def test_reference_decodes_stored_text_and_keeps_source(self):
        content = '工艺说明\nhttps://example.org/manual#page=4'
        refs = service.references({"trace": {"reference": [{
            "title": json.dumps("取心"), "content": json.dumps(content)}]}})
        self.assertEqual(refs[0]["content"], content)
        self.assertEqual(refs[0]["title"], "取心")
        self.assertEqual(refs[0]["urls"], ["https://example.org/manual#page=4"])
        self.assertEqual(refs[0]["id"], "chunk:0_0")

    def test_rules_reject_fabrication_and_invalid_citations(self):
        case = {"facts": [["无法", "缺少"]], "forbidden": ["公差为0.01"], "source_any": ["标准"]}
        result = {"answer": "缺少标准全文", "references": [{"title": "标准", "content": "目录"}],
                  "used_citations": ["chunk:0_0"], "invalid_citations": []}
        self.assertTrue(evaluate.grade(case, result)["rule_pass"])
        result["answer"] += "，公差为0.01"
        self.assertFalse(evaluate.grade(case, result)["fact_rules_pass"])
        result["invalid_citations"] = ["chunk:0_9"]
        self.assertFalse(evaluate.grade(case, result)["citation_ids_valid"])
        result.update(used_citations=[], invalid_citations=[])
        self.assertFalse(evaluate.grade(case, result)["citation_ids_valid"])

    def test_answer_reports_unknown_ids_and_rejects_partial_results(self):
        result = {"answer": '<reference id="chunk:0_9"></reference>', "status": "FINISH", "trace": {}}
        config = {"kag_solver_pipeline": {"executors": [{}]}}
        with patch.object(service.cli, "load_config", return_value=config), \
             patch.object(service.cli, "validate_config"), patch.object(service.cli, "init_runtime"), \
             patch.object(service.cli, "ask", new=AsyncMock(return_value=result)):
            actual = asyncio.run(service.answer("取心", strategy="baseline"))
            self.assertEqual(actual["invalid_citations"], ["chunk:0_9"])
            result["status"] = "RUNNING"
            with self.assertRaises(RuntimeError):
                asyncio.run(service.answer("取心", strategy="baseline"))

    def test_failed_requests_count_in_rates(self):
        summary = evaluate.summarize([
            {"mode": "hybrid", "fact_rules_pass": True, "duration_seconds": 3},
            {"mode": "hybrid", "error": "TimeoutError"}])["hybrid"]
        self.assertEqual(summary["fact_rule_rate"], 0.5)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["mean_seconds"], 3)
        self.assertEqual(summary["p95_seconds"], 3)

    def test_http_validation_busy_and_answer(self):
        with patch.object(web.cli, "load_config", return_value={}), patch.object(web.cli, "validate_config"):
            with TestClient(web.app) as client:
                self.assertEqual(client.post("/api/ask", json={"question": " "}).status_code, 422)
                self.assertEqual(client.post("/api/ask", json={"question": "问", "mode": "other"}).status_code, 422)
                asyncio.run(web.app.state.lock.acquire())
                self.assertEqual(client.post("/api/ask", json={"question": "问"}).status_code, 409)
                web.app.state.lock.release()
                with patch.object(web, "answer", new=AsyncMock(return_value={"answer": "取心说明"})):
                    response = client.post("/api/ask", json={"question": "如何取心？"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["answer"], "取心说明")


if __name__ == "__main__":
    unittest.main()
