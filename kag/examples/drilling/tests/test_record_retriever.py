# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""检查图谱定位不混井、不混深度及纯向量对照隔离。"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kag.examples.drilling.record_retriever import DrillingRecordLookup, selectors
import service


def row(key, text, label="Drilling.DrillingRecord"):
    return [json.dumps({"__label__": label, "id": key, "name": key, "text": text, "content": text})]


class RecordRetrieverTests(unittest.TestCase):
    def test_only_unambiguous_supported_well_and_one_depth_are_selected(self):
        self.assertEqual(selectors("F-11 T2的3058m附近有什么情况"), ("NO 15/9-F-11 T2", ["3058"]))
        self.assertTrue(selectors("NO 15/9-F-11 T2 钻井在3058.0米处"))
        for text in ["F-11 B 在3058m", "F-11 T2A 3058m", "F-11 T2 在2013年", "F-11 T2 泵压3058MPa", "F-11 T2 3000m和3058m"]:
            self.assertIsNone(selectors(text))

    def test_graph_paths_keep_matching_depth_and_source_and_ignore_injected_sql(self):
        retriever = object.__new__(DrillingRecordLookup)
        retriever._name = "DrillingRecordLookup"
        retriever.top_k = 6
        retriever.graph = SimpleNamespace(execute_dsl=Mock(side_effect=[
            SimpleNamespace(data=[row("matching", "Observed 20MT overpull at 3058m MD."),
                                  row("wrong-depth", "30580m MD"), row("pressure", "3058 psi")]),
            SimpleNamespace(data=[row("chunk", "Original evidence", "Drilling.Chunk")])]))
        task = SimpleNamespace(arguments={"query": "F-11 T2 在3058.0m的情况；PRIVATE_SQL_CANARY"})
        result = retriever.invoke(task)
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].chunk_id, "chunk")
        self.assertNotIn("PRIVATE_SQL_CANARY", str(retriever.graph.execute_dsl.call_args_list))
        self.assertIn("inWell", retriever.graph.execute_dsl.call_args_list[0].args[0])
        self.assertIn("source", retriever.graph.execute_dsl.call_args_list[1].args[0])

    def test_other_questions_do_not_query_graph(self):
        retriever = object.__new__(DrillingRecordLookup)
        retriever._name = "DrillingRecordLookup"
        retriever.graph = Mock()
        self.assertFalse(retriever.invoke(SimpleNamespace(arguments={"query": "取心原理是什么"})).chunks)
        retriever.graph.execute_dsl.assert_not_called()

    def test_hybrid_adds_business_lookup_without_polluting_vector_baseline(self):
        config = {"kag_solver_pipeline": {"executors": [{"retrievers": [{"type": "rc_open_spg"}]}]}}
        hybrid = service.retrieval_config(config, "hybrid")
        self.assertEqual(hybrid["kag_solver_pipeline"]["executors"][0]["retrievers"][0]["type"], "drilling_record_lookup")
        self.assertEqual(service.retrieval_config(config, "vector"), config)
        self.assertEqual(len(config["kag_solver_pipeline"]["executors"][0]["retrievers"]), 1)


if __name__ == "__main__":
    unittest.main()
