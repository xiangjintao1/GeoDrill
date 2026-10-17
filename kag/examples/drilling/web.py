# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""GeoDrill 本地工作台，只监听回环地址。"""

import asyncio
import json
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Event
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from service import DEFAULT_CONFIG, ROOT, answer, catalog, diagnose
from diagnosis import DiagnosisCase, KNOWLEDGE
import run as cli

logger = logging.getLogger(__name__)
QUERY_CONCURRENCY = 2
_query_loop = None


async def dispatch(question, mode, strategy, on_event):
    if mode == "diagnosis":
        return await diagnose(json.loads(question), on_event=on_event)
    return await answer(question, mode, strategy=strategy, on_event=on_event)


def run_isolated(question, mode, strategy, sender):
    """子进程独占配置、流水线和事件循环；只回传进度和业务结果。"""
    global _query_loop
    if _query_loop is None:
        _query_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_query_loop)
    from threading import Lock
    send_lock = Lock()
    def emit(event):
        with send_lock:
            sender.send(event)
    try:
        return _query_loop.run_until_complete(dispatch(question, mode, strategy, emit))
    finally:
        sender.close()


class QueryWorker:
    """有界进程池隔离 KAG 状态；线程仅转发子进程事件，不执行并发 KAG。"""
    def __init__(self, isolated=True):
        self.context = multiprocessing.get_context("spawn")
        self.processes = ProcessPoolExecutor(QUERY_CONCURRENCY, mp_context=self.context) if isolated else None
        self.executor = ThreadPoolExecutor(max_workers=QUERY_CONCURRENCY if isolated else 1,
                                           thread_name_prefix="drilling-query")
        self.loop = None

    def run(self, question, mode, strategy, on_event):
        if self.processes:
            receiver, sender = self.context.Pipe(duplex=False)
            try:
                future = self.processes.submit(run_isolated, question, mode, strategy, sender)
                while not future.done():
                    if receiver.poll(.02):
                        event = receiver.recv()
                        if on_event:
                            on_event(event)
                while receiver.poll():
                    event = receiver.recv()
                    if on_event:
                        on_event(event)
                return future.result()
            finally:
                receiver.close()
                sender.close()
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        return self.loop.run_until_complete(dispatch(question, mode, strategy, on_event))

    def close(self):
        def close_loop():
            if self.loop:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.run_until_complete(self.loop.shutdown_default_executor())
                self.loop.close()
        self.executor.submit(close_loop).result()
        self.executor.shutdown(wait=True)
        if self.processes:
            self.processes.shutdown(wait=True)


@asynccontextmanager
async def lifespan(app):
    config = cli.load_config(DEFAULT_CONFIG)
    cli.validate_config(config)
    app.state.lock = asyncio.Semaphore(QUERY_CONCURRENCY)
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
    if isinstance(body, DiagnosisCase):
        question, mode, strategy = body.model_dump_json(), "diagnosis", "optimized"
    else:
        question, mode, strategy = body.question.strip(), body.mode, body.strategy
    if not question:
        raise HTTPException(422, "问题不能为空")
    if app.state.lock.locked():
        raise HTTPException(409, "问答并发已满，请稍后再试")
    await app.state.lock.acquire()
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(app.state.worker.executor, app.state.worker.run,
                                      question, mode, strategy, on_event)
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


@app.get("/api/diagnosis/schema")
def diagnosis_schema():
    cases = json.loads((ROOT / "diagnosis/cases.json").read_text(encoding="utf-8"))
    return {"observations": KNOWLEDGE["observations"], "scope": KNOWLEDGE["scope"], "cases": cases["cases"]}


@app.post("/api/diagnose")
async def diagnostic_analysis(body: DiagnosisCase):
    future = await submit(body)
    try:
        return await asyncio.shield(future)
    except Exception:
        logger.exception("Diagnosis failed")
        raise HTTPException(503, "诊断图谱未就绪或分析失败，请检查 OpenSPG 并核对诊断知识版本") from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
