# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""GeoDrill 本地工作台，只监听回环地址。"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from service import DEFAULT_CONFIG, ROOT, answer, catalog
import run as cli

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    config = cli.load_config(DEFAULT_CONFIG)
    cli.validate_config(config)
    app.state.lock = asyncio.Lock()
    yield


app = FastAPI(title="GeoDrill 钻探知识工作台", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=800)
    mode: Literal["hybrid", "vector"] = "hybrid"


@app.get("/")
def index():
    return FileResponse(ROOT / "workbench.html")


@app.get("/health")
def health():
    return {"status": "ready", "app": "geodrill"}


@app.get("/api/catalog")
def materials():
    return {"items": catalog()}


@app.post("/api/ask")
async def ask(body: Question):
    if not body.question.strip():
        raise HTTPException(422, "问题不能为空")
    if app.state.lock.locked():
        raise HTTPException(409, "已有问题正在处理，请稍后再试")
    async with app.state.lock:
        try:
            # KAG 包含同步模型调用和进程级配置；单独线程执行，串行隔离不同检索模式。
            return await asyncio.to_thread(lambda: asyncio.run(answer(body.question, body.mode)))
        except Exception:
            logger.exception("Question processing failed")
            raise HTTPException(503, "问答暂未完成，请检查模型授权、知识库和本地服务后重试") from None


@app.get("/api/report")
def report():
    path = ROOT / "results/evaluation/latest.json"
    if not path.exists():
        raise HTTPException(404, "暂无评测结果")
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8090)
