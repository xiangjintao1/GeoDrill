# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""GeoDrill 本地工作台，只监听回环地址。"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from service import DEFAULT_CONFIG, ROOT, answer, catalog
import run as cli

logger = logging.getLogger(__name__)


class QueryWorker:
    """KAG 配置为进程级，使用固定工作线程和事件循环，避免跨请求复用异步限流器。"""
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="drilling-query")
        self.loop = None

    def run(self, question, mode, strategy, on_event):
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        return self.loop.run_until_complete(answer(question, mode, strategy=strategy, on_event=on_event))

    def close(self):
        def close_loop():
            if self.loop:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
                self.loop.close()
        self.executor.submit(close_loop).result()
        self.executor.shutdown(wait=True)


@asynccontextmanager
async def lifespan(app):
    config = cli.load_config(DEFAULT_CONFIG)
    cli.validate_config(config)
    app.state.lock = asyncio.Lock()
    app.state.worker = QueryWorker()
    try:
        yield
    finally:
        await asyncio.to_thread(app.state.worker.close)


app = FastAPI(title="GeoDrill 钻探知识工作台", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    mode: Literal["hybrid", "vector"] = "hybrid"
    strategy: Literal["baseline", "optimized"] = "optimized"


@app.get("/")
def index():
    return FileResponse(ROOT / "workbench.html")


@app.get("/health")
def health():
    return {"status": "ready", "app": "geodrill"}


@app.get("/api/catalog")
def materials():
    return {"items": catalog()}


async def submit(body, on_event=None):
    if not body.question.strip():
        raise HTTPException(422, "问题不能为空")
    if app.state.lock.locked():
        raise HTTPException(409, "已有问题正在处理，请稍后再试")
    await app.state.lock.acquire()
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(app.state.worker.executor, app.state.worker.run,
                                      body.question, body.mode, body.strategy, on_event)
    except BaseException:
        app.state.lock.release()
        raise
    def release(done):
        app.state.lock.release()
        if not done.cancelled():
            done.exception()  # 客户端断开后仍取走异常，后台任务结束前不释放占用。
    future.add_done_callback(release)
    return future


@app.post("/api/ask")
async def ask(body: Question):
    future = await submit(body)
    try:
        return await asyncio.shield(future)
    except Exception:
        logger.exception("Question processing failed")
        raise HTTPException(503, "问答暂未完成，请检查模型授权、知识库和本地服务后重试") from None


@app.post("/api/ask/stream")
async def ask_stream(body: Question):
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()
    disconnected = Event()
    def emit(event):
        if not disconnected.is_set():
            loop.call_soon_threadsafe(queue.put_nowait, event)
    future = await submit(body, emit)
    queue.put_nowait({"type": "stage", "stage": "initialization", "status": "started"})
    def finished(done):
        try:
            emit({"type": "result", "result": done.result()})
        except Exception:
            logger.exception("Streaming question failed")
            emit({"type": "error", "message": "问答未完成，请检查本地服务或模型授权后重试"})
    future.add_done_callback(finished)
    async def events():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    event = {"type": "heartbeat"}
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in {"result", "error"}:
                    break
        finally:
            disconnected.set()
    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/report")
def report():
    path = ROOT / "results/evaluation/latest.json"
    if not path.exists():
        raise HTTPException(404, "暂无评测结果")
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
