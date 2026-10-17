# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""按请求记录阶段耗时与模型调用，不记录提示词和凭据。"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock

CURRENT = ContextVar("drilling_query_metrics", default=None)


class QueryMetrics:
    def __init__(self, strategy="baseline", on_event=None):
        self.strategy = strategy
        self.on_event = on_event
        self.started = time.perf_counter()
        self.spans = []
        self.lock = Lock()
        self.first_answer_token_seconds = None

    def emit(self, event):
        elapsed = round(time.perf_counter() - self.started, 3)
        if event.get("type") == "delta":
            with self.lock:
                if self.first_answer_token_seconds is None:
                    self.first_answer_token_seconds = elapsed
        if self.on_event:
            self.on_event({**event, "elapsed_seconds": elapsed})

    def summary(self):
        with self.lock:
            spans = [dict(x) for x in self.spans]
        stages = {}
        for item in spans:
            stages[item["name"]] = round(stages.get(item["name"], 0) + item["seconds"], 3)
        calls = [x for x in spans if x["name"] == "model"]
        return {"stages_seconds": stages, "model_calls": len(calls), "calls": calls,
                "first_answer_token_seconds": self.first_answer_token_seconds,
                "note": "阶段存在嵌套或并行，耗时不可直接相加；未使用答案缓存。"}


@contextmanager
def stage(name, **details):
    metrics = CURRENT.get()
    record = {"name": name, **details}
    started = time.perf_counter()
    if metrics:
        metrics.emit({"type": "stage", "stage": name, "status": "started"})
    try:
        yield record
    except BaseException:
        record["failed"] = True
        raise
    finally:
        record["seconds"] = round(time.perf_counter() - started, 3)
        if metrics:
            with metrics.lock:
                metrics.spans.append(record)
            metrics.emit({"type": "stage", "stage": name, "status": "completed", "seconds": record["seconds"]})
