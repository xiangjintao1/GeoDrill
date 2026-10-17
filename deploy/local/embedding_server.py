# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""本地中文向量服务：兼容 KAG 使用的 OpenAI embeddings 接口。"""

import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastembed import TextEmbedding
from pydantic import BaseModel, Field

MODEL = "BAAI/bge-small-zh-v1.5"
CACHE = Path(os.getenv("GEODRILL_MODEL_CACHE", "D:/GeoDrill-local/models"))
LOCK = Lock()


@asynccontextmanager
async def lifespan(app):
    CACHE.mkdir(parents=True, exist_ok=True)
    app.state.embedding = TextEmbedding(MODEL, cache_dir=str(CACHE), threads=4,
                                       providers=["CPUExecutionProvider"])
    yield


app = FastAPI(title="GeoDrill local embeddings", lifespan=lifespan)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = MODEL
    encoding_format: str = "float"
    dimensions: int = Field(default=512, gt=0)


@app.get("/health")
def health():
    return {"status": "ready", "model": MODEL, "dimensions": 512}


@app.post("/v1/embeddings")
def embeddings(body: EmbeddingRequest):
    texts = [body.input] if isinstance(body.input, str) else body.input
    if body.model != MODEL or body.dimensions != 512 or body.encoding_format not in {"float", "base64"}:
        raise HTTPException(400, "Expected BAAI/bge-small-zh-v1.5, 512 dimensions, float/base64 encoding")
    if not texts or len(texts) > 64 or any(not text.strip() or len(text) > 16000 for text in texts):
        raise HTTPException(400, "Expected 1-64 nonempty texts, each at most 16000 characters")
    with LOCK:
        vectors = list(app.state.embedding.embed(texts, batch_size=16))
    return {"object": "list", "model": MODEL,
            "data": [{"object": "embedding", "index": index,
                      "embedding": vector.tolist() if body.encoding_format == "float" else
                      base64.b64encode(vector.astype("<f4").tobytes()).decode("ascii")}
                     for index, vector in enumerate(vectors)],
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9230)
