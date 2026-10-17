# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""性能优化的正确性边界：复杂任务、配置变更和请求隔离。"""

import asyncio
import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import service
from kag.examples.drilling.query_pipeline import can_generate_directly
from kag.examples.drilling.telemetry import CURRENT, QueryMetrics, stage


class PerformanceTests(unittest.TestCase):
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
