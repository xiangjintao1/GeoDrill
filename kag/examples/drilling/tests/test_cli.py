# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""无需导入 KAG 或连接外部服务的入口检查。"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("drilling_run", MODULE_DIR / "run.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class DrillingCLIValidation(unittest.TestCase):
    def config(self):
        with patch.dict(os.environ, {}, clear=True):
            config = cli.load_config(MODULE_DIR / "kag_config.yaml")
        config["project"].update(host_addr="http://localhost:8887", id="12")
        config["openie_llm"].update(base_url="https://example.com/v1", api_key="test-key", model="chat")
        config["vectorize_model"].update(base_url="https://example.com/v1", api_key="test-key", model="embedding")
        return config

    def test_environment_updates_shared_model_config(self):
        with patch.dict(os.environ, {"DRILLING_LLM_MODEL": "test-model"}, clear=True):
            config = cli.load_config(MODULE_DIR / "kag_config.yaml")
        self.assertEqual(config["chat_llm"]["model"], "test-model")
        self.assertEqual(config["kag_solver_pipeline"]["planner"]["llm"]["model"], "test-model")

    def test_numeric_id_and_dimensions_are_converted(self):
        config = self.config()
        config["vectorize_model"]["vector_dimensions"] = "1024"
        cli.validate_config(config)
        self.assertEqual(config["project"]["id"], 12)
        self.assertEqual(config["vectorizer"]["vector_dimensions"], 1024)

    def test_oauth_does_not_require_api_key_or_base_url(self):
        config = self.config()
        config["openie_llm"]["type"] = "chatgpt_oauth"
        for field in ("api_key", "base_url"):
            del config["openie_llm"][field]
        cli.validate_config(config)

    def test_rejects_incomplete_config_without_revealing_key(self):
        config = self.config()
        config["openie_llm"].update(api_key="secret-test-value", model="YOUR_CHAT_MODEL")
        with self.assertRaises(ValueError) as error:
            cli.validate_config(config)
        self.assertIn("openie_llm.model", str(error.exception))
        self.assertNotIn("secret-test-value", str(error.exception))

    def test_rejects_wrong_namespace_url_and_dimension(self):
        config = self.config()
        config["project"].update(namespace="CAZy", host_addr="localhost:8887")
        config["vectorize_model"]["vector_dimensions"] = "0"
        with self.assertRaises(ValueError) as error:
            cli.validate_config(config)
        for field in ("namespace", "host_addr", "vector_dimensions"):
            self.assertIn(field, str(error.exception))

    def test_corpus_requires_nonempty_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with self.assertRaises(ValueError):
                cli.corpus_files(path)
            (path / "sample.md").write_text("  ", encoding="utf-8")
            with self.assertRaises(ValueError):
                cli.corpus_files(path)
            (path / "sample.md").write_text("# 示例\n带来源的内容", encoding="utf-8")
            self.assertEqual(len(cli.corpus_files(path)), 1)


if __name__ == "__main__":
    unittest.main()
