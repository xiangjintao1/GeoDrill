# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""验证流式终态、后台串行隔离和事件循环复用。"""

import asyncio
import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web
from fastapi.testclient import TestClient


class StreamingTests(unittest.TestCase):
    def client(self):
        return TestClient(web.app)

    def test_deltas_are_followed_by_verified_result(self):
        async def answer(question, mode, **kwargs):
            kwargs["on_event"]({"type": "delta", "text": "岩心"})
            return {"answer": "岩心", "status": "FINISH"}
        with patch.object(web.cli, "load_config", return_value={}), patch.object(web.cli, "validate_config"), \
             patch.object(web, "answer", new=answer), self.client() as client:
            response = client.post("/api/ask/stream", json={"question": "取心"})
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[0]["type"], "stage")
            self.assertTrue(any(x["type"] == "delta" for x in events))
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["result"]["status"], "FINISH")

    def test_interrupted_generation_never_emits_success(self):
        async def answer(question, mode, **kwargs):
            kwargs["on_event"]({"type": "delta", "text": "未完成内容"})
            raise ValueError("private-upstream-error")
        with patch.object(web.cli, "load_config", return_value={}), patch.object(web.cli, "validate_config"), \
             patch.object(web, "answer", new=answer), self.client() as client, self.assertLogs(web.logger, "ERROR"):
            response = client.post("/api/ask/stream", json={"question": "取心"})
            events = [json.loads(line) for line in response.text.splitlines()]
            self.assertEqual(events[-1]["type"], "error")
            self.assertFalse(any(x["type"] == "result" for x in events))
            self.assertNotIn("private-upstream-error", response.text)

    def test_busy_worker_keeps_health_responsive_and_reuses_loop(self):
        started, release = Event(), Event()
        loops = []
        async def answer(question, mode, **kwargs):
            loops.append(asyncio.get_running_loop())
            started.set()
            await asyncio.to_thread(release.wait)
            return {"answer": "完成"}
        with patch.object(web.cli, "load_config", return_value={}), patch.object(web.cli, "validate_config"), \
             patch.object(web, "answer", new=answer), self.client() as client:
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(client.post, "/api/ask", json={"question": "取心"})
                try:
                    self.assertTrue(started.wait(timeout=5))
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.post("/api/ask", json={"question": "钻头"}).status_code, 409)
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=5).status_code, 200)
            self.assertEqual(client.post("/api/ask", json={"question": "钻头"}).status_code, 200)
            self.assertIs(loops[0], loops[1])
