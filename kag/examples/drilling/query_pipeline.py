# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""保留 KAG 规划和检索，用请求级计时定位耗时。"""

from kag.interface import ExecutorABC, SolverPipelineABC
from kag.solver.pipeline.kag_static_pipeline import KAGStaticPipeline
from kag.solver.executor.retriever.kag_hybrid_retrieval_executor import KAGHybridRetrievalExecutor
from kag.examples.drilling.telemetry import CURRENT, stage


def can_generate_directly(task):
    """多跳或推理任务仍需中间摘要；仅最终输出前的检索可直接交给生成器。"""
    return all(child.executor == "Output" and not child.children for child in task.children)


@SolverPipelineABC.register("drilling_profiled_pipeline")
class DrillingPipeline(KAGStaticPipeline):
    async def planning(self, query, context, **kwargs):
        with stage("planning"):
            return await super().planning(query, context, **kwargs)

    async def execute_task(self, query, task, context, **kwargs):
        with stage("task." + task.executor):
            metrics = CURRENT.get()
            if metrics and metrics.strategy == "optimized" and task.executor == "Output" and not task.children:
                task.update_result("最终答案由生成器统一根据检索原文及任务结果输出。")
                return
            return await super().execute_task(query, task, context, **kwargs)


@ExecutorABC.register("drilling_profiled_retriever")
class DrillingRetriever(KAGHybridRetrievalExecutor):
    def do_retrieval(self, *args, **kwargs):
        with stage("retrieval"):
            result = super().do_retrieval(*args, **kwargs)
        metrics = CURRENT.get()
        if metrics:
            metrics.emit({"type": "retrieved", "chunks": len(result.chunks), "graphs": len(result.graphs),
                          "titles": list(dict.fromkeys(str(x.title) for x in result.chunks))[:8]})
        return result

    def do_summary(self, task_query, tag_id, task, retrieved_data, context, **kwargs):
        metrics = CURRENT.get()
        if metrics and metrics.strategy == "optimized" and can_generate_directly(task):
            return retrieved_data
        return super().do_summary(task_query, tag_id, task, retrieved_data, context, **kwargs)
