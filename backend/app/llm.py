"""模型调用层。上游全部按 OpenAI 兼容接口访问。"""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from .config import settings

DEFAULT_NOTE_TEMPLATE = """请根据下面内容整理阅读笔记，用简体中文，按这个结构输出 Markdown：
1. 这段讲了什么
2. 关键方法或结论
3. 我的疑问与解答

原文：
{原文}

问答：
{问答}

只依据给定内容，不要补充外部知识。"""

class ConfigError(RuntimeError):
    """缺少模型配置时直接抛出，让请求失败，不做静默降级。"""


def _client(base_url: str, api_key: str, label: str) -> OpenAI:
    if not base_url or not api_key:
        raise ConfigError(f"未配置{label}的 base_url / api_key，请检查 .env")
    return OpenAI(base_url=base_url, api_key=api_key, timeout=180.0, max_retries=2)


def test_chat_route(base_url: str, api_key: str, model: str) -> None:
    """配置页保存前做一次最小对话请求。"""
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=20.0, max_retries=0)
    client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=1,
    )


def list_models(base_url: str, api_key: str) -> list[str]:
    """读取 OpenAI 兼容服务的模型列表。"""
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=20.0, max_retries=0)
    response = client.models.list()
    return sorted(
        {item.id for item in response.data if getattr(item, "id", "")},
        key=str.lower,
    )


def _with_agent_profile(system: str) -> str:
    """把 data/agent.md 的用户设定追加到对话模型系统提示里。"""
    path = settings.data_path / "agent.md"
    if not path.exists():
        return system
    profile = path.read_text(encoding="utf-8").strip()
    if not profile:
        return system
    return f"{system}\n\n用户自定义 Agent 设定（agent.md）：\n{profile}"


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.2,
) -> str:
    base_url = base_url or settings.chat_base_url
    api_key = api_key or settings.chat_api_key
    model = model or settings.chat_model
    if not model:
        raise ConfigError("未配置 CHAT_MODEL")
    response = _client(base_url, api_key, "对话模型").chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def translate(text: str, target_language: str = "简体中文") -> str:
    base_url, api_key, model = settings.translation_route()
    system = (
        f"你是学术论文翻译。把用户给的原文翻译成{target_language}，保持专业术语准确，"
        "保留数学符号和公式原样，不要添加解释，只输出译文。"
    )
    return chat(
        [{"role": "system", "content": system}, {"role": "user", "content": text}],
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.1,
    )


def answer_with_context(
    question: str,
    context: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    system = (
        "你是 PaperLens。只依据下面编号的原文片段回答问题。"
        "回答要直接给结论和依据，不要输出引用编号、页码标记或来源角标。"
        "原文没有提到的内容，直接回答原文没有提及。\n\n"
        f"编号原文片段：\n{context}"
    )
    system = _with_agent_profile(system)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for item in (history or [])[-8:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": question})
    return chat(messages)


def summarize_reading(text: str, dialogue: str, template: str = "") -> str:
    prompt = (template or DEFAULT_NOTE_TEMPLATE).strip()
    if "{原文}" not in prompt:
        prompt += "\n\n原文：\n{原文}"
    if "{问答}" not in prompt:
        prompt += "\n\n问答：\n{问答}"
    system = _with_agent_profile(
        "你在整理一段论文的阅读笔记。只依据给定内容，不要补充任何外部知识。"
    )
    user = prompt.replace("{原文}", text).replace("{问答}", dialogue or "（无）")
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}])


def document_overview(context: str) -> dict[str, Any]:
    """从论文内容抽取列表页展示用的结构化信息。"""
    system = (
        "你是论文信息抽取器。只依据给定原文输出 JSON，不要输出 Markdown 代码块。"
        "JSON 必须包含 summary、methods、problems、conclusion 四个字段；"
        "summary 和 conclusion 是字符串，methods 和 problems 是字符串数组。"
    )
    raw = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"论文原文：\n{context}"},
        ],
        temperature=0.1,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError("论文详情生成失败：模型返回的不是有效 JSON") from exc
    return {
        "summary": str(result.get("summary", "")),
        "methods": [str(item) for item in result.get("methods", [])],
        "problems": [str(item) for item in result.get("problems", [])],
        "conclusion": str(result.get("conclusion", "")),
    }

