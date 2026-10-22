"""检索与问答。

全文问答使用本地关键词检索，不需要额外向量模型；段落问答直接取该段及前后各两段。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from . import db, llm

# 全文检索取回的段落数。
TOP_K = 8
# 段落模式向前后各扩展的段落数。
NEIGHBOUR_SPAN = 2
# 送进模型的上下文字符上限，超出就截断。
CONTEXT_CHAR_LIMIT = 16000


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
        text = block["text"].strip()
        if not text:
            continue
        header = f"[{index}] (第 {block['page'] + 1} 页) "
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


def retrieve(doc_id: str, question: str, block_id: str | None) -> list[dict[str, Any]]:
    blocks = db.get_blocks(doc_id)
    by_id = {b["id"]: b for b in blocks}

    if block_id is not None and block_id in by_id:
        anchor = by_id[block_id]
        lo = max(0, anchor["order_index"] - NEIGHBOUR_SPAN)
        hi = anchor["order_index"] + NEIGHBOUR_SPAN + 1
        return [b for b in blocks if lo <= b["order_index"] < hi]

    return rank_blocks(blocks, question)


def ask(
    doc_id: str,
    question: str,
    *,
    block_id: str | None,
    scope: str,
) -> dict[str, Any]:
    """scope 为 block 时只看当前段及邻段，为 full 时走全文关键词检索。"""
    anchor = block_id if scope == "block" else None
    context_blocks = retrieve(doc_id, question, anchor)
    if not context_blocks:
        raise llm.ConfigError("没有可用于回答的段落")

    context = _clip(context_blocks)
    if not context.strip():
        raise llm.ConfigError("检索到的段落都是空的，无法作答")

    history = db.get_messages(doc_id, block_id)
    answer = llm.answer_with_context(question, context, history)
    citations = [
        {"block_id": b["id"], "page": b["page"], "text": b["text"][:160]}
        for b in context_blocks
    ]
    return {"answer": answer, "citations": citations}


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

