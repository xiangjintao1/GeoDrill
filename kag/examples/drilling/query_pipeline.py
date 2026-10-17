# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""保留 KAG 规划和检索，用请求级计时定位耗时。"""

import re
from copy import copy
from contextvars import copy_context

from kag.interface import ExecutorABC, SolverPipelineABC, Task
from kag.solver.pipeline.kag_static_pipeline import KAGStaticPipeline
from kag.solver.executor.retriever.kag_hybrid_retrieval_executor import KAGHybridRetrievalExecutor
from kag.examples.drilling.telemetry import CURRENT, stage


def can_generate_directly(task):
    """多跳或推理任务仍需中间摘要；仅最终输出前的检索可直接交给生成器。"""
    return all(child.executor == "Output" and not child.children for child in task.children)


def is_simple_question(query):
    """只让明确的单项地学问答走快捷路径，不确定时保留规划。"""
    if len(query) > 120 or re.search(
        r"比较|对比|区别|分别|计算|推算|先.*再|根据.*选择|以及|并且|[;；\n]|[?？].+\S", query
    ):
        return False
    domain = re.search(r"钻|取心|岩心|泥浆|含水率|GB/T|NQ", query, re.I)
    intent = re.search(r"是什么|为什么|多少|能否|能.*吗|就能|是否|列出|尺寸|公差|型号|原理", query)
    return bool(domain and intent)


class RequestRetriever:
    """仅包装本次调用，让框架内部的检索线程继承请求计时上下文。"""
    def __init__(self, retriever):
        self.retriever = retriever
        self.context = copy_context()

    def __getattr__(self, name):
        return getattr(self.retriever, name)

    def invoke(self, *args, **kwargs):
        return self.context.copy().run(self.retriever.invoke, *args, **kwargs)


@SolverPipelineABC.register("drilling_profiled_pipeline")
class DrillingPipeline(KAGStaticPipeline):
    async def planning(self, query, context, **kwargs):
        with stage("planning"):
            metrics = CURRENT.get()
            direct = metrics and metrics.strategy == "optimized" and is_simple_question(query)
            if metrics:
                metrics.emit({"type": "route", "route": "direct" if direct else "planned"})
            if direct:
                retrieval = Task("Retriever", {"query": query}, id="1")
                output = Task("Output", {"query": query}, parents=[retrieval], id="2")
                retrieval.add_child(output)
                return [retrieval, output]
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
            scoped = copy(self)
            scoped.retrievers = [RequestRetriever(retriever) for retriever in self.retrievers]
            result = KAGHybridRetrievalExecutor.do_retrieval(scoped, *args, **kwargs)
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
