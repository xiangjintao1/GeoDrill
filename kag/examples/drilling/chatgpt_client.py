# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""把 KAG 的文本提示词交给官方 ChatGPT 套餐 Responses 接口。"""

import asyncio
import atexit
import time
from functools import lru_cache

from openai import OpenAI
from kag.interface.common.llm_client import LLMClient
from kag.interface.solver.reporter_abc import do_report
from kag.examples.drilling.chatgpt_auth import RESOURCE, access_token
from kag.examples.drilling.telemetry import CURRENT, stage


@lru_cache(maxsize=1)
def shared_client():
    # SDK 在发出请求时调用凭据提供函数，连接池可复用，刷新后的凭据也能立即生效。
    client = OpenAI(api_key=access_token, base_url=RESOURCE, max_retries=0, timeout=120)
    atexit.register(client.close)
    return client


def response_input(prompt, messages=None):
    if messages is None:
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
    if not messages:
        raise ValueError("模型输入不能为空")
    result = []
    for message in messages:
        role, content = message.get("role", "user"), message.get("content", "")
        if role not in {"user", "assistant", "system", "developer"} or not isinstance(content, str):
            raise ValueError("此适配器只支持文本消息")
        result.append({"role": "developer" if role == "system" else role, "content": content})
    return result


def collect_response(events, on_delta=None):
    parts, usage, completed = [], None, False
    for event in events:
        if event.type == "response.output_text.delta":
            parts.append(event.delta)
            if on_delta:
                on_delta(event.delta)
        elif event.type == "response.completed":
            completed, usage = True, event.response.usage
        elif event.type in {"response.failed", "response.incomplete", "error"}:
            # 只输出错误类型，不将完整服务响应或鉴权信息写入日志。
            raise ValueError(f"ChatGPT 调用未完成：{event.type}")
    if not completed:
        raise ValueError("ChatGPT 响应中断，未收到完成事件")
    answer = "".join(parts)
    if not answer.strip():
        raise ValueError("ChatGPT 未返回文本答案")
    return answer, usage


@LLMClient.register("chatgpt_oauth")
class ChatGPTClient(LLMClient):
    def __init__(self, model: str, **kwargs):
        super().__init__(name="drilling-chatgpt", **kwargs)
        self.model = model

    def __call__(self, prompt="", **kwargs):
        if kwargs.get("tools") or kwargs.get("image_url"):
            raise ValueError("钻探适配器仅支持文本调用")
        role = "generation" if kwargs.get("segment_name") == "answer" else "planning" if kwargs.get("segment_name") == "thinker" else "intermediate"
        metrics = CURRENT.get()
        with stage("model", role=role) as record:
            started = time.perf_counter()
            def on_delta(delta):
                record.setdefault("first_token_seconds", round(time.perf_counter() - started, 3))
                if metrics and role == "generation":
                    metrics.emit({"type": "delta", "text": delta})
            baseline = metrics and metrics.strategy == "baseline"
            client = OpenAI(api_key=access_token(), base_url=RESOURCE, max_retries=0, timeout=120) if baseline else shared_client()
            try:
                with client.responses.create(model=self.model, input=response_input(prompt, kwargs.get("messages")),
                                             store=False, stream=True) as events:
                    answer, usage = collect_response(events, on_delta)
            finally:
                if baseline:
                    client.close()
            if usage:
                record.update(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
        if usage:
            self.get_token_meter().update(usage.output_tokens, usage.input_tokens, usage.total_tokens)
        do_report(answer, "FINISH", **kwargs)
        return answer

    async def acall(self, prompt="", **kwargs):
        return await asyncio.to_thread(self, prompt, **kwargs)
