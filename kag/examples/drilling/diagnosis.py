# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""结构化工况与三值条件检查；事实、未知和不符线索分别保留。"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KNOWLEDGE_PATH = Path(__file__).with_name("diagnosis") / "knowledge.json"
KNOWLEDGE = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
KNOWLEDGE_HASH = hashlib.sha256(KNOWLEDGE_PATH.read_bytes()).hexdigest()


class DiagnosisCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: dict[str, Literal["yes", "no", "unknown"]] = Field(default_factory=dict)

    @field_validator("observations")
    @classmethod
    def known_fields(cls, observations):
        if observations.keys() - KNOWLEDGE["observations"].keys():
            raise ValueError("含有未定义的观测字段")
        return observations


def reason(case, knowledge):
    """逐规则检查合取条件，不把缺失当否定，也不输出概率或确定诊断。"""
    candidates = []
    for rule in knowledge["rules"]:
        groups = {"yes": [], "no": [], "unknown": []}
        for field in rule["requires"]:
            groups[case.observations.get(field, "unknown")].append({
                "field": field, "label": knowledge["observations"][field]})
        status = "conflicting" if groups["no"] else "incomplete" if groups["unknown"] else "compatible"
        paths = [{"observation": item["field"], "value": value, "rule": rule["id"],
                  "hypothesis": rule["name"], "source": rule["source"]}
                 for value, items in groups.items() for item in items]
        candidates.append({"id": rule["id"], "name": rule["name"], "status": status,
            "support": groups["yes"], "counterevidence": groups["no"],
            "missing": groups["unknown"], "paths": paths, "source_id": rule["source"]})
    # 只针对已有支持线索且没有不符条件的候选追问；全未知时先补基本现象。
    fields = list(dict.fromkeys(item["field"] for candidate in candidates
        if candidate["support"] and not candidate["counterevidence"] for item in candidate["missing"]))
    if not fields and not any(value != "unknown" for value in case.observations.values()):
        fields = ["stuck", "circulation_restricted", "pump_pressure_rise", "lost_returns"]
    return {"candidates": candidates, "follow_up": [
        {"field": field, "question": knowledge["observations"][field] + "？"} for field in fields],
        "sources": knowledge["sources"], "scope": knowledge["scope"],
        "conclusion": "线索相容性分析，尚未确认原因；不同异常可以并存，不输出现场处置参数。"}
