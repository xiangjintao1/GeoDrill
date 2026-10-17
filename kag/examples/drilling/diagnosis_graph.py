# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""通过 KAG KGWriter 写入知识，通过 OpenSPG 图接口读取规则及证据邻居。"""

import argparse
import json

from diagnosis import KNOWLEDGE, KNOWLEDGE_HASH


def graph_data():
    nodes, edges = [], []
    def node(key, name, label, **properties):
        nodes.append({"id": key, "name": name, "label": label, "properties": properties})
        return nodes[-1]
    def edge(start, relation, end):
        edges.append({"id": "", "from": start["id"], "fromType": start["label"], "to": end["id"],
                      "toType": end["label"], "label": relation, "properties": {}})
    root = node("diagnosis-v1", f"钻井异常机制检查 v{KNOWLEDGE['version']}", "DiagnosticKnowledge",
                version=KNOWLEDGE_HASH, desc=KNOWLEDGE["scope"])
    conditions = {field: node(field, label, "DiagnosticCondition", fieldName=field)
                  for field, label in KNOWLEDGE["observations"].items()}
    sources = {source["id"]: node(source["id"], source["title"], "DiagnosticSource",
        sourceUrl=source["url"], desc=source["summary"], verified=source["verified"])
        for source in KNOWLEDGE["sources"]}
    rules = {rule["id"]: node(rule["id"], rule["name"], "DiagnosticRule", logic="ALL")
             for rule in KNOWLEDGE["rules"]}
    for rule in KNOWLEDGE["rules"]:
        current = rules[rule["id"]]
        edge(root, "hasRule", current)
        for field in rule["requires"]:
            edge(current, "requiresCondition", conditions[field])
        edge(current, "supportedBy", sources[rule["source"]])
        for parent in rule.get("requires_rules", []):
            edge(current, "requiresMechanism", rules[parent])
    for record in KNOWLEDGE["cases"]:
        current = node(record["id"], record["name"], "DiagnosticCase", domain=record["domain"],
            sourceUrl=record["source_url"], anchor=record["anchor"],
            observations=json.dumps(record["observations"], ensure_ascii=False),
            facts=json.dumps(record["facts"], ensure_ascii=False),
            limitations=json.dumps(record["limitations"], ensure_ascii=False))
        edge(root, "hasCase", current)
        for field in record["observations"]:
            edge(current, "hasObservation", conditions[field])
    return {"resultNodes": nodes, "resultEdges": edges}


def load_graph(host_addr, project_id):
    from kag.common.tools.graph_api.impl.openspg_graph_api import OpenSPGGraphApi, convert_node_to_json

    graph = OpenSPGGraphApi(host_addr=host_addr, project_id=project_id)
    table = graph.execute_dsl("""
        MATCH (k:`Drilling.DiagnosticKnowledge`)-[:hasRule]->(r:`Drilling.DiagnosticRule`)
              -[:requiresCondition]->(c:`Drilling.DiagnosticCondition`)
        WHERE k.id = 'diagnosis-v1'
        RETURN k.version,r.id,r.name,r.logic,c.fieldName
    """)
    def decode(value):
        return json.loads(value) if isinstance(value, str) and value.startswith('"') else value
    rules, sources = {}, {}
    for row in table.data:
        version, key, name, logic, field = map(decode, row)
        if version != KNOWLEDGE_HASH or logic != "ALL" or field not in KNOWLEDGE["observations"]:
            raise ValueError("Diagnostic graph version or condition mismatch")
        rule = rules.setdefault(key, {"id": key, "name": name, "requires": []})
        if field not in rule["requires"]:
            rule["requires"].append(field)
    evidence = graph.execute_dsl("""
        MATCH (r:`Drilling.DiagnosticRule`)-[:supportedBy]->(s:`Drilling.DiagnosticSource`)
        RETURN r.id,s
    """)
    for key, raw_source in evidence.data:
        key = decode(key)
        if key not in rules:
            continue
        prop = {name: decode(value) for name, value in convert_node_to_json(raw_source)["propertyValues"].items()}
        source_id = prop["id"]
        if "source" in rules[key] and rules[key]["source"] != source_id:
            raise ValueError("Diagnostic rule has ambiguous evidence")
        rules[key]["source"] = source_id
        sources[source_id] = {"id": source_id, "title": prop["name"], "url": prop["sourceUrl"],
                              "summary": prop["desc"], "verified": prop["verified"]}
    dependencies = graph.execute_dsl("""
        MATCH (r:`Drilling.DiagnosticRule`)-[:requiresMechanism]->(p:`Drilling.DiagnosticRule`)
        RETURN r.id,p.id
    """)
    for child, parent in dependencies.data:
        child, parent = decode(child), decode(parent)
        if child not in rules or parent not in rules:
            raise ValueError("Diagnostic mechanism dependency is incomplete")
        rules[child].setdefault("requires_rules", []).append(parent)
    expected = {rule["id"]: rule for rule in KNOWLEDGE["rules"]}
    if rules.keys() != expected.keys() or any(
        set(rule["requires"]) != set(expected[key]["requires"]) or rule.get("source") != expected[key]["source"]
        or rule["name"] != expected[key]["name"]
        or set(rule.get("requires_rules", [])) != set(expected[key].get("requires_rules", []))
        for key, rule in rules.items()
    ):
        raise ValueError("Diagnostic graph missing or incomplete; run diagnosis_graph.py")
    if sources != {source["id"]: source for source in KNOWLEDGE["sources"]}:
        raise ValueError("Diagnostic source content differs from the verified manifest")
    records = graph.execute_dsl("""
        MATCH (k:`Drilling.DiagnosticKnowledge`)-[:hasCase]->(c:`Drilling.DiagnosticCase`)
        WHERE k.id = 'diagnosis-v1'
        RETURN c
    """)
    cases = []
    for row in records.data:
        prop = {name: decode(value) for name, value in convert_node_to_json(row[0])["propertyValues"].items()}
        cases.append({"id": prop["id"], "name": prop["name"], "domain": prop["domain"],
                      "source_url": prop["sourceUrl"], "anchor": prop["anchor"],
                      **{key: json.loads(prop[key]) for key in ["observations", "facts", "limitations"]}})
    observed_edges = graph.execute_dsl("""
        MATCH (c:`Drilling.DiagnosticCase`)-[:hasObservation]->(o:`Drilling.DiagnosticCondition`)
        RETURN c.id,o.fieldName
    """)
    expected_edges = {(case["id"], field) for case in cases for field in case["observations"]}
    if {(decode(row[0]), decode(row[1])) for row in observed_edges.data} != expected_edges or (
        sorted(cases, key=lambda case: case["id"]) != sorted(KNOWLEDGE["cases"], key=lambda case: case["id"])
    ):
        raise ValueError("Diagnostic case facts differ from the verified manifest")
    return {**KNOWLEDGE, "rules": [rules[key] for key in expected],
            "sources": list(sources.values()), "cases": cases}


def main():
    import run as cli
    from kag.builder.model.sub_graph import SubGraph
    from kag.builder.component.writer.kg_writer import KGWriter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=cli.Path, default=cli.PROJECT_DIR / "kag_config.local.yaml")
    args = parser.parse_args()
    config = cli.load_config(args.config)
    cli.validate_config(config)
    cli.init_runtime(config)
    cli.commit_schema(config)
    KGWriter().invoke(SubGraph.from_dict(graph_data()), write_ckpt=False)
    knowledge = load_graph(config["project"]["host_addr"], config["project"]["id"])
    print(json.dumps({"rules": len(knowledge["rules"]), "sources": len(knowledge["sources"]),
                      "cases": len(knowledge["cases"])}))


if __name__ == "__main__":
    main()
