# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""在 KAG 扩展接口上组合图谱读取、条件推理和可追溯输出。"""

from kag.interface import Context, ExecutorABC, SolverPipelineABC, Task
from kag.interface.solver.planner_abc import TaskStatus
from kag.examples.drilling.telemetry import stage
from diagnosis import DiagnosisCase, reason
from diagnosis_graph import load_graph


@ExecutorABC.register("drilling_diagnosis_graph")
class DiagnosticGraph(ExecutorABC):
    def __init__(self, host_addr: str, project_id: int):
        super().__init__()
        self.host_addr, self.project_id = host_addr, project_id

    def invoke(self, query, task, context, **kwargs):
        with stage("diagnosis.graph"):
            knowledge = load_graph(self.host_addr, self.project_id)
        task.update_result(knowledge)
        return knowledge


@ExecutorABC.register("drilling_diagnosis_rules")
class DiagnosticRules(ExecutorABC):
    def invoke(self, query, task, context, **kwargs):
        with stage("diagnosis.reasoning"):
            result = reason(DiagnosisCase.model_validate(query), task.parents[0].result)
        task.update_result(result)
        return result


@SolverPipelineABC.register("drilling_diagnosis_pipeline")
class DiagnosticPipeline(SolverPipelineABC):
    def __init__(self, graph: ExecutorABC, reasoning: ExecutorABC):
        super().__init__()
        self.graph, self.reasoning = graph, reasoning

    async def ainvoke(self, query, **kwargs):
        context = Context()
        graph = Task("DiagnosticGraph", {}, id="graph")
        reasoning = Task("DiagnosticRules", {}, parents=[graph], id="reasoning")
        graph.add_child(reasoning)
        context.add_task(graph)
        context.add_task(reasoning)
        await self.graph.ainvoke(query, graph, context)
        graph.status = TaskStatus.SUCCESS
        result = await self.reasoning.ainvoke(query, reasoning, context)
        reasoning.status = TaskStatus.SUCCESS
        result["trace"] = [
            {"task": graph.id, "executor": graph.executor, "depends_on": [], "status": graph.status.value},
            {"task": reasoning.id, "executor": reasoning.executor, "depends_on": [graph.id], "status": reasoning.status.value}]
        return result
