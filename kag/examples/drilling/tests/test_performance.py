# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""性能优化的正确性边界：复杂任务、配置变更和请求隔离。"""

import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
from benchmark_latency import summarize
from kag.examples.drilling.query_pipeline import can_generate_directly, is_simple_question, DrillingPipeline, DrillingRetriever
from kag.interface.solver.retriever_abc import RetrieverOutput
from kag.examples.drilling.telemetry import CURRENT, QueryMetrics, stage


class PerformanceTests(unittest.TestCase):
    def test_business_adapter_propagates_metrics_through_framework_thread_pool(self):
        def retrieve(*args, **kwargs):
            self.assertIs(CURRENT.get(), metrics)
            with stage("model", role="retrieval"):
                pass
            return RetrieverOutput()
        original = [SimpleNamespace(name=name, priority=0, invoke=retrieve) for name in ["graph", "vector"]]
        retriever = object.__new__(DrillingRetriever)
        retriever.retrievers = original
        retriever.merger = SimpleNamespace(invoke=lambda *args, **kwargs: RetrieverOutput())
        retriever.do_data_report = Mock()
        metrics = QueryMetrics("optimized")
        token = CURRENT.set(metrics)
        try:
            result = retriever.do_retrieval("取心", "test", None, None)
            self.assertIsInstance(result, RetrieverOutput)
            self.assertEqual(metrics.summary()["model_calls"], 2)
            self.assertIs(retriever.retrievers, original)
        finally:
            CURRENT.reset(token)
        self.assertIsNone(CURRENT.get())

    def test_router_preserves_complex_and_unknown_questions(self):
        for query in ["元深1井使用的NR826M钻头直径是多少毫米？", "绳索取心为什么不用起出全部钻杆？"]:
            self.assertTrue(is_simple_question(query))
        for query in ["比较两种取心工艺的成本", "根据地层选择钻头并计算钻压", "天气是什么",
                      "钻头是什么？取心是什么？", "分别列出NQ与HQ的尺寸"]:
            self.assertFalse(is_simple_question(query))

    def test_direct_route_skips_planner_and_keeps_request_local_tasks(self):
        planner = SimpleNamespace(ainvoke=AsyncMock(return_value=[]))
        pipeline = DrillingPipeline(planner, [], None)
        async def work():
            token = CURRENT.set(QueryMetrics("optimized"))
            try:
                first = await pipeline.planning("钻头直径是多少？", None)
                second = await pipeline.planning("取心原理是什么？", None)
                planner.ainvoke.assert_not_awaited()
                self.assertIsNot(first[0], second[0])
                self.assertIs(first[0].children[0], first[1])
                self.assertIs(first[1].parents[0], first[0])
                await pipeline.planning("比较两种取心工艺", None)
                planner.ainvoke.assert_awaited_once()
            finally:
                CURRENT.reset(token)
        asyncio.run(work())

    def test_latency_report_does_not_exclude_errors_from_quality_rates(self):
        report = summarize([
            {"strategy": "baseline", "duration_seconds": 5, "performance": {"model_calls": 4}, "rule_pass": True},
            {"strategy": "baseline", "error": "TimeoutError"},
            {"strategy": "optimized", "error": "TimeoutError"}])
        self.assertEqual(report["baseline"]["rule_pass_rate"], .5)
        self.assertEqual(report["baseline"]["mean_model_calls"], 4)
        self.assertEqual(report["optimized"]["errors"], 1)
        self.assertIsNone(report["optimized"]["mean_seconds"])

    def test_complex_dependencies_keep_intermediate_summary(self):
        leaf = SimpleNamespace(executor="Output", children=[])
        self.assertTrue(can_generate_directly(SimpleNamespace(children=[leaf])))
        for executor in ["Retriever", "Deduce"]:
            self.assertFalse(can_generate_directly(SimpleNamespace(children=[
                SimpleNamespace(executor=executor, children=[])])))
        self.assertFalse(can_generate_directly(SimpleNamespace(children=[
            SimpleNamespace(executor="Output", children=[leaf])])))

    def test_metrics_propagate_to_worker_threads_without_leaking(self):
        async def work():
            metrics = QueryMetrics()
            token = CURRENT.set(metrics)
            try:
                def operation():
                    with stage("retrieval"):
                        pass
                await asyncio.to_thread(operation)
                self.assertIn("retrieval", metrics.summary()["stages_seconds"])
            finally:
                CURRENT.reset(token)
            self.assertIsNone(CURRENT.get())
        asyncio.run(work())

    def test_pipeline_reuse_and_config_invalidation(self):
        config = {"project": {"id": 1}, "kag_solver_pipeline": {
            "planner": {"plan_prompt": {}}, "executors": [{}]}}
        result = {"answer": "证据不足", "status": "FINISH", "trace": {}}
        with patch.object(service, "_configuration", None), patch.dict(service._pipelines, {}, clear=True), \
             patch.object(service.cli, "load_config", side_effect=lambda _: copy.deepcopy(config)), \
             patch.object(service.cli, "validate_config"), patch.object(service.cli, "init_runtime") as initialize, \
             patch.object(service.cli, "create_pipeline", return_value=object()) as create, \
             patch.object(service.cli, "ask", new=AsyncMock(side_effect=lambda *a, **k: copy.deepcopy(result))):
            async def work():
                first = await service.answer("取心")
                second = await service.answer("钻头")
                self.assertFalse(first["runtime_reused"])
                self.assertTrue(second["runtime_reused"])
                self.assertEqual(create.call_count, 1)
                config["project"]["id"] = 2
                third = await service.answer("取心")
                self.assertFalse(third["runtime_reused"])
                self.assertEqual(create.call_count, 2)
                self.assertEqual(initialize.call_count, 2)
            asyncio.run(work())
