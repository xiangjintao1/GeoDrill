# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""验证流式终态、进程状态隔离、授权刷新和事件循环复用。"""

import asyncio
import json
import os
import tempfile
import time
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web
from fastapi.testclient import TestClient


def isolated_probe(question, mode, strategy, sender):
    """在真实子进程内替换外部模型，验证 IPC、配置和循环归属。"""
    import service
    service._configuration = question
    async def fake_answer(query, mode, **kwargs):
        kwargs["on_event"]({"type": "delta", "text": query})
        await asyncio.sleep(.5)
        return {"answer": service._configuration, "pid": os.getpid(),
                "loop": id(asyncio.get_running_loop())}
    web.answer = fake_answer
    return web.run_isolated(question, mode, strategy, sender)


def refresh_probe(directory):
    import chatgpt_auth as auth
    auth.STORE = Path(directory)
    record_file = auth.STORE / "fake-account.json"
    count_file = auth.STORE / "refresh-count.txt"
    def exchange(_):
        count_file.write_text(str(int(count_file.read_text()) + 1))
        time.sleep(.3)
        return {"access_token": "refreshed-test-token", "expires_at": time.time() + 3600}
    with patch.object(auth, "read_record", side_effect=lambda: json.loads(record_file.read_text())), \
         patch.object(auth, "save_record", side_effect=lambda record: record_file.write_text(json.dumps(record))), \
         patch.object(auth, "exchange", side_effect=exchange):
        return auth.access_token()


class ProcessIsolationTests(unittest.TestCase):
    def test_expired_credential_is_refreshed_once_across_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fake-account.json").write_text(json.dumps({"access_token": "expired-test-token",
                "expires_at": 0, "client_id": "test", "refresh_token": "test-refresh"}))
            (root / "refresh-count.txt").write_text("0")
            with web.ProcessPoolExecutor(2, mp_context=web.multiprocessing.get_context("spawn")) as pool:
                futures = [pool.submit(refresh_probe, directory) for _ in range(2)]
                self.assertEqual([future.result(timeout=30) for future in futures], ["refreshed-test-token"] * 2)
            self.assertEqual((root / "refresh-count.txt").read_text(), "1")

    def test_two_queries_use_separate_process_state_and_streams(self):
        worker = web.QueryWorker()
        events = {"A": [], "B": []}
        try:
            with patch.object(web, "run_isolated", new=isolated_probe), ThreadPoolExecutor(2) as pool:
                futures = {key: pool.submit(worker.run, key, "hybrid", "optimized", events[key].append)
                           for key in events}
                results = {key: future.result(timeout=30) for key, future in futures.items()}
            self.assertNotEqual(results["A"]["pid"], results["B"]["pid"])
            for key in events:
                self.assertEqual(results[key]["answer"], key)
                self.assertEqual(events[key], [{"type": "delta", "text": key}])
        finally:
            worker.close()


class StreamingTests(unittest.TestCase):
    def setUp(self):
        # HTTP 单元测试使用本地替身；进程隔离由单独测试和真实接口回归覆盖。
        original = web.QueryWorker
        self.worker_patch = patch.object(web, "QueryWorker", side_effect=lambda: original(isolated=False))
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)
        self.concurrency_patch = patch.object(web, "QUERY_CONCURRENCY", 1)
        self.concurrency_patch.start()
        self.addCleanup(self.concurrency_patch.stop)

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

    def test_cancelled_request_keeps_worker_busy_until_completion(self):
        started, release = Event(), Event()
        async def answer(question, mode, **kwargs):
            started.set()
            await asyncio.to_thread(release.wait)
            return {"answer": "完成"}
        async def work():
            worker = web.QueryWorker()
            lock = asyncio.Lock()
            with patch.object(web.app.state, "worker", worker, create=True), \
                 patch.object(web.app.state, "lock", lock, create=True), patch.object(web, "answer", new=answer):
                request = asyncio.create_task(web.ask(web.Question(question="取心")))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 5))
                    request.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await request
                    self.assertTrue(lock.locked())
                    with self.assertRaises(web.HTTPException) as caught:
                        await web.submit(web.Question(question="钻头"))
                    self.assertEqual(caught.exception.status_code, 409)
                finally:
                    release.set()
                    await asyncio.to_thread(worker.close)
                self.assertFalse(lock.locked())
        asyncio.run(work())
