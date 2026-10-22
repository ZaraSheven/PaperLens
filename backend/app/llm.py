"""模型调用层。上游全部按 OpenAI 兼容接口访问。"""
from __future__ import annotations

import base64
import json
from collections.abc import Iterator
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
    messages: list[dict[str, Any]],
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


def _answer_messages(
    question: str,
    context: str,
    history: list[dict[str, Any]] | None,
    image: bytes | None,
) -> list[dict[str, Any]]:
    """问答要发给模型的消息。同步和流式走同一套，免得两边提示词走偏。"""
    system = (
        "你是 PaperLens。用户点着论文里的某一段提问，要解释的就是那一段。"
        "下面编号的片段来自整篇论文，最前面的几条就是用户点的那一段和它前后的内容。"
        "每个片段开头都写明它在第几页、属于正文 / 公式 / 图 / 表格。"
        "公式、图和表格在界面上显示的是页面原图，片段里的文字是从那一块抽出来的，可能残缺甚至为空。"
        "随问题一起发来的那张图就是用户点的那一块的原图："
        "直接把图里的结构、标签、坐标轴、符号读出来，结合片段里的正文解释它在讲什么。"
        "没有附带原图时不要凭空描述图里画了什么，说明哪一部分需要看原图即可。"
        "用户问的正是一段公式、一张图或一张表格时，不要回答「原文没有提及」。"
        "数学公式一律写成 LaTeX，行内用 $...$，独立成行的用 $$...$$，不要用纯文本拼公式。"
        "回答要直接给结论和依据，不要输出引用编号、页码标记或来源角标。"
        "其余问题按原文回答，原文确实没提到的，就回答原文没有提及。\n\n"
        f"编号原文片段：\n{context}"
    )
    system = _with_agent_profile(system)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for item in (history or [])[-8:]:
        messages.append({"role": item["role"], "content": item["content"]})
    if image is None:
        messages.append({"role": "user", "content": question})
    else:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image).decode("ascii")
                        },
                    },
                ],
            }
        )
    return messages


def answer_with_context(
    question: str,
    context: str,
    history: list[dict[str, Any]] | None = None,
    image: bytes | None = None,
) -> str:
    return chat(_answer_messages(question, context, history, image))


def answer_with_context_stream(
    question: str,
    context: str,
    history: list[dict[str, Any]] | None = None,
    image: bytes | None = None,
) -> Iterator[str]:
    """一段一段地吐答案，界面边收边显示，不用等整段生成完。"""
    model = settings.chat_model
    if not model:
        raise ConfigError("未配置 CHAT_MODEL")
    stream = _client(settings.chat_base_url, settings.chat_api_key, "对话模型").chat.completions.create(
        model=model,
        messages=_answer_messages(question, context, history, image),  # type: ignore[arg-type]
        temperature=0.2,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content
        if piece:
            yield piece


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

