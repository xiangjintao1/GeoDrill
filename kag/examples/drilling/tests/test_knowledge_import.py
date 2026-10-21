# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""验证来源指纹、开发/评测隔离、原文完整性和图谱回读。"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knowledge_import as importer


class KnowledgeImportTests(unittest.TestCase):
    def test_local_sources_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            root.mkdir()
            outside = Path(directory) / "outside.txt"
            outside.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                importer.local_file(root, "../outside.txt")

    def workbook(self, cached, original=None):
        def book(rows):
            return SimpleNamespace(worksheets=[SimpleNamespace(title="Sheet1", iter_rows=lambda **kw: iter(rows))], close=Mock())
        return patch("openpyxl.load_workbook", side_effect=[book(cached), book(original or cached)])

    def test_workbook_ignores_empty_excel_columns_and_keeps_missing_zero_and_duplicates(self):
        rows = [("feature", "target", None), (None, 0, None), (3, 2, None), (3, 2, None)]
        with self.workbook(rows):
            result = importer.workbook_profile(Path("unused"), "target")
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["columns"], ["feature", "target"])
        self.assertEqual(result["missing_by_column"]["feature"], 1)
        self.assertEqual(result["target_zero"], 1)
        self.assertEqual(result["target_positive"], 2)
        self.assertEqual(result["duplicate_rows"], 1)

    def test_formula_cache_policy_is_explicit_and_missing_cache_fails(self):
        raw = [("feature", "target"), ("=1+2", "Partial Loss")]
        with self.workbook([("feature", "target"), (3, "Partial Loss")], raw):
            result = importer.workbook_profile(Path("unused"), "target")
        self.assertEqual(result["formula_by_column"], {"feature": 1})
        self.assertEqual(result["label_counts"], {"Partial Loss": 1})
        with self.workbook([("feature", "target"), (None, "Partial Loss")], raw):
            with self.assertRaisesRegex(ValueError, "缓存"):
                importer.workbook_profile(Path("unused"), "target")

    def test_unnamed_data_and_missing_target_fail(self):
        for rows in [[("feature", "target", None), (1, 2, 3)], [("feature", "target"), (1, None)]]:
            with self.workbook(rows), self.assertRaises(ValueError):
                importer.workbook_profile(Path("unused"), "target")

    def test_prepare_imports_only_development_well_and_checks_hash(self):
        def csv_file(path, rows):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ddr.parquet"
            source.write_bytes(b"test-source")
            config = {"development_well": "DEV", "split_manifest": "split.csv", "datasets": [
                {"id": "volve-ddr", "path": "ddr.parquet", "sha256": importer.digest(source), "source_url": "https://example.org/ddr"}]}
            sources = root / "sources.json"
            sources.write_text(json.dumps(config), encoding="utf-8")
            csv_file(root / "split.csv", [{"wellbore_id": "DEV", "split": "development"}, {"wellbore_id": "HOLDOUT", "split": "test_a"}])
            csv_file(root / "01_inventory/download_manifest.csv", [{"local_path": "ddr.parquet", "sha256": importer.digest(source)}])
            csv_file(root / "01_inventory/well_event_screening_evidence.csv", [{"wellbore_id": "DEV", "source_kind": "activity", "doc_name": "dev-report", "activity_start": "start", "activity_end": "end", "category": "loss"}])
            record = {"nameWellbore": "DEV", "docName": "dev-report", "dTimStart": "report-start", "dTimEnd": "report-end",
                      "activity": [{"dTimStart": "start", "dTimEnd": "end", "comments": "Original evidence", "state": "ok", "stateDetailActivity": "mud loss"}]}
            table = SimpleNamespace(to_pylist=lambda: [record, {**record, "nameWellbore": "HOLDOUT", "docName": "test-report"}])
            with patch.object(importer, "SOURCES", sources), patch("pyarrow.parquet.read_table", return_value=table):
                result = importer.prepare(root)
                self.assertEqual(result["datasets"][0]["profile"]["source_reports"], 2)
                self.assertEqual(len(result["records"]), 2)
                self.assertTrue(all(row["well"] == "DEV" for row in result["records"]))
                self.assertEqual(result["records"][1]["categories"], ["loss"])
                self.assertNotIn("observations", result["records"][1])
                source.write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "指纹"):
                    importer.prepare(root)

    def test_graph_retains_long_text_and_separates_original_state_from_candidate(self):
        dataset = {"id": "d", "name": "Dataset", "source_url": "https://example.org/source", "sha256": "hash",
                   "attribution": "Publisher", "license": "CC BY", "task": "Retrospective", "limitations": "No causal label", "profile": {}}
        record = {"id": "r", "well": "DEV", "dataset": "d", "source_url": dataset["source_url"], "anchor": "doc:activity[0]",
                  "kind": "activity", "text": "A" * 2500 + "END_OF_EVIDENCE", "start": "start", "end": "end", "report_start": "later", "report_end": "later-end",
                  "state": "ok", "detail": "mud loss", "categories": ["loss"]}
        graph, catalog = importer.graph_data({"datasets": [dataset], "records": [record]})
        activity = next(node for node in graph["resultNodes"] if node["label"] == "DrillingRecord")
        self.assertEqual(activity["properties"]["state"], "ok")
        self.assertNotIn("DiagnosticCondition", str(graph))
        self.assertIn("END_OF_EVIDENCE", "".join(row["content"] for row in catalog))
        self.assertIn("不构成确认异常", catalog[-1]["content"] if len(catalog) == 1 else catalog[1]["content"])
        self.assertEqual(graph, importer.graph_data({"datasets": [dataset], "records": [record]})[0])

    def test_graph_verification_requires_nodes_and_relations(self):
        graph = {"resultNodes": [{"id": "record", "label": "DrillingRecord"}],
                 "resultEdges": [{"from": "record", "to": "dataset", "label": "fromDataset"}]}
        with patch("kag.common.tools.graph_api.impl.openspg_graph_api.OpenSPGGraphApi") as api:
            api.return_value.execute_dsl.return_value = SimpleNamespace(data=[])
            with self.assertRaisesRegex(ValueError, "节点"):
                importer.verify_graph(graph, {})
            api.return_value.execute_dsl.side_effect = [SimpleNamespace(data=[['"record"']]), SimpleNamespace(data=[])]
            with self.assertRaisesRegex(ValueError, "关系"):
                importer.verify_graph(graph, {})

    def test_text_chunks_prefer_complete_lines_without_dropping_content(self):
        text = "head\n" + "a" * 700 + '\n  "Seepage Loss": 12880,\n' + "tail" * 200
        parts = list(importer.text_parts(text))
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(part) <= 1000 for part in parts))
        self.assertTrue(any('"Seepage Loss": 12880' in part for part in parts))


if __name__ == "__main__":
    unittest.main()
