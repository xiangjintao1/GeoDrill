# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""验证三值观测、异常并存、证据完整性与案例答案隔离。"""

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagnosis import DiagnosisCase, KNOWLEDGE, reason, related_cases
from diagnosis_graph import graph_data, load_graph
from kag.examples.drilling.diagnosis_pipeline import DiagnosticGraph, DiagnosticRules, DiagnosticPipeline
import web
from fastapi.testclient import TestClient


class DiagnosisTests(unittest.TestCase):
    def analyze(self, **observations):
        return {item["id"]: item for item in reason(DiagnosisCase(observations=observations), KNOWLEDGE)["candidates"]}

    def test_unknown_is_not_negative_or_confirmed(self):
        unknown = self.analyze(stuck="yes")["differential"]
        self.assertEqual(unknown["status"], "incomplete")
        self.assertFalse(unknown["counterevidence"])
        negative = self.analyze(stuck="yes", overbalance="no")["differential"]
        self.assertEqual(negative["status"], "conflicting")
        self.assertEqual(negative["counterevidence"][0]["field"], "overbalance")

    def test_multiple_mechanisms_can_coexist(self):
        candidates = self.analyze(circulation_restricted="yes", pump_pressure_rise="yes",
                                  lost_returns="yes", natural_path="yes")
        self.assertEqual(candidates["packoff"]["status"], "compatible")
        self.assertEqual(candidates["natural-loss"]["status"], "compatible")
        self.assertEqual(candidates["induced-loss"]["status"], "incomplete")

    def test_missing_observations_generate_questions_without_guessing(self):
        result = reason(DiagnosisCase(), KNOWLEDGE)
        self.assertTrue(result["follow_up"])
        self.assertTrue(all(item["status"] == "incomplete" for item in result["candidates"]))
        self.assertNotIn("confidence", str(result))

    def test_case_input_rejects_labels_and_unknown_fields(self):
        for body in [{"observations": {"stuck": True}}, {"observations": {"invented": "yes"}},
                     {"observations": {}, "author_analysis": "answer"}]:
            with self.assertRaises(ValueError):
                DiagnosisCase.model_validate(body)

    def test_graph_missing_never_falls_back_to_local_rules(self):
        with patch("kag.common.tools.graph_api.impl.openspg_graph_api.OpenSPGGraphApi") as graph:
            graph.return_value.execute_dsl.return_value = SimpleNamespace(data=[])
            with self.assertRaises(ValueError):
                load_graph("http://localhost", 1)

    def test_builder_graph_has_real_rule_condition_and_source_edges(self):
        from kag.builder.model.sub_graph import SubGraph
        graph = SubGraph.from_dict(graph_data())
        self.assertTrue(any(node.label == "DiagnosticCase" for node in graph.nodes))
        self.assertTrue(any(edge.label == "requiresMechanism" for edge in graph.edges))
        self.assertTrue(any(edge.label == "hasObservation" for edge in graph.edges))
        self.assertNotIn("author_analysis", str(graph.to_dict()))

    def test_kag_pipeline_passes_graph_result_to_reasoning_task(self):
        with patch("kag.examples.drilling.diagnosis_pipeline.load_graph", return_value=copy.deepcopy(KNOWLEDGE)):
            pipeline = DiagnosticPipeline(DiagnosticGraph("http://localhost", 1), DiagnosticRules())
            result = asyncio.run(pipeline.ainvoke({"observations": {"stuck": "yes"}}))
        self.assertEqual(result["trace"][1]["depends_on"], ["graph"])
        self.assertTrue(all(task["status"] == "SUCCESS" for task in result["trace"]))
        self.assertEqual(len(result["candidates"]), 6)
        self.assertTrue(result["related_cases"])

    def test_real_case_examples_preserve_uncertainty_and_split_labels(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / "diagnosis/cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len({case["id"] for case in cases}), 8)
        for case in cases:
            self.assertTrue(case["author_analysis"] and case["source_url"] and case["limitations"])
            DiagnosisCase(observations=case["observations"])

    def test_dependency_chain_is_order_independent_and_does_not_invent_observations(self):
        knowledge = copy.deepcopy(KNOWLEDGE)
        knowledge["rules"].reverse()
        case = DiagnosisCase(observations={"stuck": "yes", "circulation_restricted": "yes", "pump_pressure_rise": "yes"})
        result = reason(case, knowledge)
        linked = next(item for item in result["candidates"] if item["id"] == "packoff-sticking")
        self.assertEqual(linked["status"], "compatible")
        self.assertEqual(linked["inference_path"], ["packoff", "packoff-sticking"])
        self.assertNotIn("obstruction", case.observations)

    def test_unknown_or_conflicting_parent_blocks_indirect_support(self):
        self.assertEqual(self.analyze(stuck="yes")["packoff-sticking"]["status"], "incomplete")
        self.assertEqual(self.analyze(stuck="yes", circulation_restricted="no")["packoff-sticking"]["status"], "conflicting")
        follow_up = reason(DiagnosisCase(observations={"stuck": "yes"}), KNOWLEDGE)["follow_up"]
        question = next(item for item in follow_up if item["field"] == "circulation_restricted")
        self.assertIn("packoff-sticking", question["affects"])

    def test_cycle_and_missing_parent_fail_without_hanging(self):
        for dependency in ["packoff-sticking", "nonexistent"]:
            knowledge = copy.deepcopy(KNOWLEDGE)
            knowledge["rules"][-1]["requires_rules"] = [dependency]
            with self.assertRaises(ValueError):
                reason(DiagnosisCase(), knowledge)

    def test_comparison_uses_facts_only_and_retains_conflicts_and_unknowns(self):
        knowledge = copy.deepcopy(KNOWLEDGE)
        record = knowledge["cases"][0]
        record["author_analysis"] = "CANARY_ANSWER_DO_NOT_USE"
        record["observations"]["pump_pressure_rise"] = "unknown"
        knowledge["cases"] = [record]
        case = DiagnosisCase(observations={"stuck": "yes", "circulation_restricted": "no", "pump_pressure_rise": "yes"})
        result = related_cases(case, knowledge)
        self.assertEqual(result[0]["agreements"], ["stuck"])
        self.assertEqual(result[0]["conflicts"], ["circulation_restricted"])
        self.assertEqual(result[0]["unrecorded"], ["pump_pressure_rise"])
        self.assertNotIn("CANARY", str(result))
        self.assertFalse(related_cases(DiagnosisCase(), knowledge))
        self.assertFalse(related_cases(case, knowledge, excluded_ids=[record["id"]]))

    def test_http_diagnosis_validates_input_and_hides_internal_errors(self):
        original = web.QueryWorker
        async def fail(*args, **kwargs):
            raise RuntimeError("private-graph-error")
        with patch.object(web.cli, "load_config", return_value={}), patch.object(web.cli, "validate_config"), \
             patch.object(web, "QueryWorker", side_effect=lambda: original(isolated=False)), \
             patch.object(web, "diagnose", new=fail), TestClient(web.app) as client:
            self.assertEqual(client.get("/api/diagnosis/schema").status_code, 200)
            self.assertEqual(client.post("/api/diagnose", json={"observations": {"stuck": True}}).status_code, 422)
            with self.assertLogs(web.logger, "ERROR"):
                response = client.post("/api/diagnose", json={"observations": {"stuck": "yes"}})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private-graph-error", response.text)


if __name__ == "__main__":
    unittest.main()
