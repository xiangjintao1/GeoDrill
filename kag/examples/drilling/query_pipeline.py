# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""保留 KAG 规划和检索，用请求级计时定位耗时。"""

from kag.interface import ExecutorABC, SolverPipelineABC
from kag.solver.pipeline.kag_static_pipeline import KAGStaticPipeline
from kag.solver.executor.retriever.kag_hybrid_retrieval_executor import KAGHybridRetrievalExecutor
from kag.examples.drilling.telemetry import stage


@SolverPipelineABC.register("drilling_profiled_pipeline")
class DrillingPipeline(KAGStaticPipeline):
    async def planning(self, query, context, **kwargs):
        with stage("planning"):
            return await super().planning(query, context, **kwargs)

    async def execute_task(self, query, task, context, **kwargs):
        with stage("task." + task.executor):
            return await super().execute_task(query, task, context, **kwargs)


@ExecutorABC.register("drilling_profiled_retriever")
class DrillingRetriever(KAGHybridRetrievalExecutor):
    def do_retrieval(self, *args, **kwargs):
        with stage("retrieval"):
            result = super().do_retrieval(*args, **kwargs)
        return result
