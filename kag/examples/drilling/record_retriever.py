# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""针对明确井号和深度，沿井筒—作业记录—原文关系查询。"""

import json
import re
from decimal import Decimal

from kag.interface import RetrieverABC
from kag.interface.solver.retriever_abc import ChunkData, RetrieverOutput


def selectors(query):
    if not re.search(r"(?<![A-Za-z0-9])F[-_\s]*11[-_\s]*T2(?![A-Za-z0-9])", query, re.I):
        return None
    depths = re.findall(r"(?<![\d.])(\d{2,5}(?:\.\d+)?)\s*(?:m(?![A-Za-z])|米)", query, re.I)
    return ("NO 15/9-F-11 T2", depths) if len(depths) == 1 else None


def decode(value):
    return json.loads(value) if isinstance(value, str) and value.startswith('"') else value


@RetrieverABC.register("drilling_record_lookup")
class DrillingRecordLookup(RetrieverABC):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.graph = None

    def schema(self):
        return {"name": "DrillingRecordLookup", "description": "按明确井号和深度读取原始记录及来源"}

    def invoke(self, task, **kwargs):
        selected = selectors(task.arguments.get("query", ""))
        if selected is None:
            return RetrieverOutput(retriever_method=self.name)
        from kag.common.tools.graph_api.impl.openspg_graph_api import OpenSPGGraphApi, convert_node_to_json

        if self.graph is None:
            self.graph = OpenSPGGraphApi(host_addr=self.kag_project_config.host_addr,
                                        project_id=self.kag_project_config.project_id)
        well, depths = selected
        # 井名由识别器的固定白名单返回，深度仅用于原文匹配，不拼接用户SQL。
        records = self.graph.execute_dsl(f"""
            MATCH (r:`Drilling.DrillingRecord`)-[:inWell]->(w:`Drilling.Wellbore`)
            WHERE w.id = '{well}' RETURN r
        """)
        depth = format(Decimal(depths[0]).normalize(), "f")
        suffix = r"(?:\.0+)?" if "." not in depth else ""
        pattern = re.compile(r"(?<![\d.])" + re.escape(depth) + suffix + r"\s*(?:m(?![A-Za-z])|米)", re.I)
        keys = []
        for row in records.data:
            props = {key: decode(value) for key, value in convert_node_to_json(row[0])["propertyValues"].items()}
            if pattern.search(props.get("text", "")) and re.fullmatch(r"[\w:-]+", props["id"]):
                keys.append(props["id"])
        chunks = []
        for key in sorted(keys)[:self.top_k]:
            evidence = self.graph.execute_dsl(f"""
                MATCH (r:`Drilling.DrillingRecord`)-[:source]->(c:`Drilling.Chunk`)
                WHERE r.id = '{key}' RETURN c
            """)
            for row in evidence.data:
                props = {name: decode(value) for name, value in convert_node_to_json(row[0])["propertyValues"].items()}
                chunks.append(ChunkData(chunk_id=props["id"], title=props["name"], content=props["content"], score=1.0))
        return RetrieverOutput(chunks=chunks, retriever_method=self.name)
