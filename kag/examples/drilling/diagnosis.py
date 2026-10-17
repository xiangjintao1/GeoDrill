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
# 诊断图谱只包含事发观测；作者复盘结论不参与推理或案例匹配。
CASE_FIELDS = ("id", "name", "domain", "source_url", "anchor", "observations", "facts", "limitations")
CASE_RECORDS = json.loads(KNOWLEDGE_PATH.with_name("cases.json").read_text(encoding="utf-8"))["cases"]
KNOWLEDGE["cases"] = [{key: item[key] for key in CASE_FIELDS} for item in CASE_RECORDS]
KNOWLEDGE_HASH = hashlib.sha256(json.dumps(
    KNOWLEDGE, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")).hexdigest()


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
    """按依赖顺序检查合取条件；间接线索不提升为现场观测事实。"""
    candidates = []
    pending = list(knowledge["rules"])
    resolved = {}
    while pending:
        available = [rule for rule in pending if set(rule.get("requires_rules", [])) <= resolved.keys()]
        if not available:
            raise ValueError("诊断规则有循环依赖或缺失的前置规则")
        rule = available[0]
        pending.remove(rule)
        groups = {"yes": [], "no": [], "unknown": []}
        for field in rule["requires"]:
            groups[case.observations.get(field, "unknown")].append({
                "field": field, "label": knowledge["observations"][field]})
        dependencies = [{"id": key, "name": resolved[key]["name"], "status": resolved[key]["status"]}
                        for key in rule.get("requires_rules", [])]
        if groups["no"] or any(item["status"] == "conflicting" for item in dependencies):
            status = "conflicting"
        elif groups["unknown"] or any(item["status"] != "compatible" for item in dependencies):
            status = "incomplete"
        else:
            status = "compatible"
        paths = [{"observation": item["field"], "value": value, "rule": rule["id"],
                  "hypothesis": rule["name"], "source": rule["source"]}
                 for value, items in groups.items() for item in items]
        candidate = {"id": rule["id"], "name": rule["name"], "status": status,
            "support": groups["yes"], "counterevidence": groups["no"],
            "missing": groups["unknown"], "paths": paths, "source_id": rule["source"],
            "dependencies": dependencies,
            "inference_path": [step for key in rule.get("requires_rules", [])
                               for step in resolved[key]["inference_path"]] + [rule["id"]]}
        candidates.append(candidate)
        resolved[rule["id"]] = candidate
    # 只针对已有支持线索且没有不符条件的候选追问；全未知时先补基本现象。
    def needed_fields(candidate):
        if candidate["status"] == "conflicting":
            return []
        return [item["field"] for item in candidate["missing"]] + [
            field for parent in candidate["dependencies"] for field in needed_fields(resolved[parent["id"]])]
    fields = list(dict.fromkeys(field for candidate in candidates if candidate["support"]
                                for field in needed_fields(candidate)))
    if not fields and not any(value != "unknown" for value in case.observations.values()):
        fields = ["stuck", "circulation_restricted", "pump_pressure_rise", "lost_returns"]
    affected = {field: [item["id"] for item in candidates if field in needed_fields(item)] for field in fields}
    fields.sort(key=lambda field: -len(affected[field]))
    return {"candidates": candidates, "follow_up": [
        {"field": field, "question": knowledge["observations"][field] + "？", "affects": affected[field]} for field in fields],
        "sources": knowledge["sources"], "scope": knowledge["scope"],
        "conclusion": "线索相容性分析，尚未确认原因；不同异常可以并存，不输出现场处置参数。"}


def related_cases(case, knowledge, excluded_ids=()):
    """仅对照已知观测；未知不计一致，矛盾显式保留，不使用作者结论排序。"""
    known = {field: value for field, value in case.observations.items() if value != "unknown"}
    results = []
    for record in knowledge["cases"]:
        if record["id"] in excluded_ids:
            continue
        shared = known.keys() & record["observations"].keys()
        agreements = sorted(field for field in shared if record["observations"][field] == known[field])
        conflicts = sorted(field for field in shared if record["observations"][field] not in {known[field], "unknown"})
        if not agreements:
            continue
        results.append({**{key: record[key] for key in CASE_FIELDS}, "agreements": agreements, "conflicts": conflicts,
                        "unrecorded": sorted(field for field in known
                                             if record["observations"].get(field, "unknown") == "unknown")})
    return sorted(results, key=lambda item: (len(item["conflicts"]), -len(item["agreements"]), item["id"]))[:3]
