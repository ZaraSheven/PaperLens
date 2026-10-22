"""检索层自检：确认超长段落不会把上下文挤成空的。

直接运行：.venv\\Scripts\\python.exe backend\\tests\\test_rag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import rag  # noqa: E402


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"  通过  {label}")


def block(page: int, text: str) -> dict:
    return {"page": page, "text": text, "id": f"b{page}", "order_index": page}


def main() -> None:
    huge = block(0, "长" * (rag.CONTEXT_CHAR_LIMIT * 2))
    clipped = rag._clip([huge])
    check("超长段落不会把上下文挤空", bool(clipped.strip()))
    check("截断后不超过上限", len(clipped) <= rag.CONTEXT_CHAR_LIMIT + 8)
    check("保留了编号和页码标记", clipped.startswith("[1] (第 1 页)"))

    many = [block(i, "正文" * 2000) for i in range(20)]
    joined = rag._clip(many)
    check("多段时总量受限", len(joined) <= rag.CONTEXT_CHAR_LIMIT + 64)
    check("多段时首段仍在", joined.startswith("[1] (第 1 页)"))

    empty = rag._clip([block(0, "")])
    check("全空段落得到空上下文，交给上层报错", not empty.strip())

    candidates = [
        block(0, "The experiment evaluates mapping accuracy."),
        block(1, "Hand-eye calibration recovers rotation and translation."),
        block(2, "The dataset contains camera and LiDAR recordings."),
    ]
    ranked = rag.rank_blocks(candidates, "How are rotation and translation calibrated?", 2)
    check("关键词检索能把相关段落排在前面", ranked[0]["id"] == "b1")

    print("\n检索层自检通过")


if __name__ == "__main__":
    main()

