"""一个最小的 OpenAI 兼容假服务，只在测试里用。

用途：在没有真实 API key 的情况下，把翻译、问答、整理笔记这三条链路完整跑一遍，
确认请求拼装、消息落库顺序、引用回传都是对的。

它只被 backend/tests 下的脚本启动，不属于产品代码，不会出现在运行时路径上。
"""
from __future__ import annotations

import hashlib
import json
import math
import socket
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI

app = FastAPI()

# 每次请求都记下来，测试据此断言「同一个问题只送给模型一次」这类行为。
RECEIVED: list[dict[str, Any]] = []


@app.get("/v1/models")
def models() -> dict[str, Any]:
    RECEIVED.append({"models": True})
    return {
        "object": "list",
        "data": [
            {"id": "fake-chat", "object": "model", "owned_by": "fake"},
            {"id": "fake-translate", "object": "model", "owned_by": "fake"},
        ],
    }


@app.post("/v1/chat/completions")
def chat(body: dict[str, Any]) -> dict[str, Any]:
    RECEIVED.append(body)
    messages = body.get("messages", [])
    last = messages[-1]["content"] if messages else ""
    system = messages[0]["content"] if messages else ""
    if "论文信息抽取器" in system:
        content = json.dumps(
            {
                "summary": "这是一篇用于测试的论文。",
                "methods": ["关键词检索", "段落级问答"],
                "problems": ["验证详情缓存", "验证引用"],
                "conclusion": "测试模型返回了结构化详情。",
            },
            ensure_ascii=False,
        )
    elif "引用格式测试" in last:
        content = f"假回答：{last[:40]} [p1]"
    else:
        content = f"假回答：{last[:60]}"
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": body.get("model", "fake"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


@app.post("/v1/embeddings")
def embeddings(body: dict[str, Any]) -> dict[str, Any]:
    RECEIVED.append(body)
    payload = body.get("input")
    texts = [payload] if isinstance(payload, str) else list(payload or [])
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": _vector(text)}
            for index, text in enumerate(texts)
        ],
        "model": body.get("model", "fake"),
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


def _vector(text: str, size: int = 64) -> list[float]:
    """按字符三元组做词袋，让内容相近的文本得到相近的向量。

    用 md5 分桶而不是内置 hash，后者带随机盐，跨进程结果会变。
    """
    lowered = text.lower()
    counts = [0.0] * size
    for index in range(max(1, len(lowered) - 2)):
        trigram = lowered[index : index + 3]
        counts[int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16) % size] += 1.0
    norm = math.sqrt(sum(value * value for value in counts)) or 1.0
    return [value / norm for value in counts]


def start(port: int = 8899) -> None:
    """后台起服务，并等到端口真的能连上再返回。"""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"假模型服务没能在 {port} 端口起来")

