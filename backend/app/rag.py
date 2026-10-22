"""检索与问答。

全文问答使用本地关键词检索，不需要额外向量模型；段落问答直接取该段及前后各两段。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from . import db, llm, parser
from .config import settings

# 全文检索取回的段落数。
TOP_K = 8
# 段落模式向前后各扩展的段落数。
NEIGHBOUR_SPAN = 2
# 送进模型的上下文字符上限，超出就截断。
CONTEXT_CHAR_LIMIT = 16000

# 片段开头写明这一块是什么。公式、图和表格在界面上显示的是原图，模型只能拿到
# 从里面抽出来的文字，有的图干脆一个字都抽不到。不写清楚，模型只会回一句
# 「原文没有提及」，用户点了图问它，等于白问。
KIND_LABEL = {"text": "正文", "formula": "公式", "figure": "图", "table": "表格"}
KIND_EMPTY = {
    "formula": "这一块在页面上是一个公式，界面上显示原图；这一块没有抽到文字。",
    "figure": "这一块在页面上是一张图，界面上显示原图；图里的文字没有抽出来。",
    "table": "这一块在页面上是一张表格，界面上显示原图；单元格文字没有抽出来。",
}


def _terms(text: str) -> list[str]:
    """英文取词，中文取双字；不依赖分词模型。"""
    lowered = text.lower()
    terms = re.findall(r"[a-z0-9]{2,}", lowered)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            terms.append(run)
        else:
            terms.extend(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def rank_blocks(
    blocks: list[dict[str, Any]], question: str, top_k: int = TOP_K
) -> list[dict[str, Any]]:
    """按关键词重叠度排序，取最相关的段落。"""
    query = Counter(_terms(question))
    if not query:
        return blocks[:top_k]
    documents = [Counter(_terms(block["text"])) for block in blocks]
    document_count = len(blocks)
    scores: list[tuple[float, dict[str, Any]]] = []
    for block, terms in zip(blocks, documents):
        score = 0.0
        for term, weight in query.items():
            frequency = terms.get(term, 0)
            if not frequency:
                continue
            appearing = sum(1 for document in documents if term in document)
            inverse_frequency = math.log((document_count + 1) / (appearing + 1)) + 1
            score += weight * (1 + math.log(frequency)) * inverse_frequency
        if score > 0:
            scores.append((score, block))
    if not scores:
        return blocks[:top_k]
    scores.sort(key=lambda item: item[0], reverse=True)
    return [block for _score, block in scores[:top_k]]


def _clip(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    used = 0
    for index, block in enumerate(blocks, start=1):
        kind = str(block.get("kind") or "text")
        text = block["text"].strip()
        if not text:
            # 空正文什么都不带，直接不要；空图/空公式要留着，它本身就是内容。
            if kind == "text":
                continue
            text = KIND_EMPTY.get(kind, KIND_EMPTY["figure"])
        header = f"[{index}] (第 {block['page'] + 1} 页 · {KIND_LABEL.get(kind, '正文')}) "
        room = CONTEXT_CHAR_LIMIT - used - len(header)
        if room <= 1:
            break
        if len(text) > room:
            # 单个段落就超过预算时截断它，而不是整段丢掉。丢掉的话超长段落会让上下文
            # 变成空的，模型在没有任何原文的情况下凭空作答。
            text = text[: room - 1] + "…"
        parts.append(header + text)
        used += len(header) + len(text)
    return "\n\n".join(parts)


def retrieve(
    doc_id: str,
    question: str,
    block_id: str | None,
) -> list[dict[str, Any]]:
    """挑出要交给模型的段落。

    用户点着某一段提问时，问题问的就是那一段（文字、图、公式或表格），答案是拿整篇
    去找依据：先把锚点那一段和它前后各两段排在前面，再补上关键词命中的其他段落。
    锚点一漏，问「这幅图讲了什么」就只能得到「原文没有提及」。

    没有锚点（整篇对话）时就是纯粹的全篇检索。
    """
    blocks = db.get_blocks(doc_id)
    anchor = next((b for b in blocks if b["id"] == block_id), None)
    ranked = rank_blocks(blocks, question)
    if anchor is None:
        return ranked

    lo = max(0, anchor["order_index"] - NEIGHBOUR_SPAN)
    hi = anchor["order_index"] + NEIGHBOUR_SPAN + 1
    window = [b for b in blocks if lo <= b["order_index"] < hi]
    seen = {block["id"] for block in window}
    return window + [block for block in ranked if block["id"] not in seen]


def ask(
    doc_id: str,
    question: str,
    *,
    block_id: str | None,
) -> dict[str, Any]:
    """block_id 是用户点的那一段；没有它就是在整篇对话面板里提问。"""
    prepared = prepare(doc_id, question, block_id=block_id)
    answer = llm.answer_with_context(
        question, prepared["context"], prepared["history"], prepared["image"]
    )
    return {"answer": answer, "citations": prepared["citations"]}


def prepare(doc_id: str, question: str, *, block_id: str | None) -> dict[str, Any]:
    """问答和流式问答共用的准备：上下文、历史，以及要一起发过去的原图。

    流式回答没法先把答案算好再落库，所以「先把问题存下来、答案边生成边发」这件事
    由接口层负责，这里只把料备齐。
    """
    context_blocks = retrieve(doc_id, question, block_id)
    if not context_blocks:
        raise llm.ConfigError("没有可用于回答的段落")

    context = _clip(context_blocks)
    if not context.strip():
        raise llm.ConfigError("检索到的段落都是空的，无法作答")

    anchor = db.get_block(block_id) if block_id else None
    return {
        "context": context,
        "history": db.get_messages(doc_id, block_id),
        "image": _anchor_image(doc_id, anchor),
        "citations": [
            {"block_id": block["id"], "page": block["page"], "text": block["text"][:160]}
            for block in context_blocks
        ],
    }


def _anchor_image(doc_id: str, block: dict[str, Any] | None) -> bytes | None:
    """问图、公式、表格时，把那一块的原图截出来一起交给模型。

    正文不需要：文字本来就抽得准，再塞一张图只是多花 token。公式和图表的文字抽不准，
    让模型直接看原图比让它猜快得多、也准得多。
    """
    if block is None or block.get("kind", "text") == "text" or not settings.chat_vision:
        return None
    path = settings.data_path / f"{doc_id}.pdf"
    if not path.exists():
        return None
    try:
        return parser.render_block_png(str(path), int(block["page"]), block)
    except Exception:
        # 裁图失败不该把整个问答打断：退回只看文字的答案，它依然是有效的。
        return None


def reading_note(block_id: str) -> str:
    block = db.get_block(block_id)
    if not block:
        raise ValueError("段落不存在")
    messages = db.get_messages(block["doc_id"], block_id)
    dialogue = "\n\n".join(f"{m['role']}：{m['content']}" for m in messages)
    template = db.get_setting("note_template", "")
    return llm.summarize_reading(block["text"], dialogue, template)


def document_context(doc_id: str) -> str:
    """取论文开头和结尾的段落做列表页详情抽取。"""
    blocks = [block for block in db.get_blocks(doc_id) if block["text"].strip()]
    selected = blocks[:24]
    tail = blocks[-8:]
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for block in selected + tail:
        if block["id"] in seen:
            continue
        seen.add(block["id"])
        merged.append(block)
    return _clip(merged)

