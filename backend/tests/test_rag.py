"""检索层自检：确认超长段落不会把上下文挤成空的。

直接运行：.venv\\Scripts\\python.exe backend\\tests\\test_rag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import rag  # noqa: E402


def check(label: str, condition: bool, extra: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} {extra}".strip())
    print(f"  通过  {label}")


def block(
    page: int,
    text: str,
    kind: str = "text",
    order: int | None = None,
    name: str | None = None,
) -> dict:
    return {
        "page": page,
        "text": text,
        "id": name or f"b{page}",
        "order_index": page if order is None else order,
        "kind": kind,
    }


def main() -> None:
    huge = block(0, "长" * (rag.CONTEXT_CHAR_LIMIT * 2))
    clipped = rag._clip([huge])
    check("超长段落不会把上下文挤空", bool(clipped.strip()))
    check("截断后不超过上限", len(clipped) <= rag.CONTEXT_CHAR_LIMIT + 8)
    check("保留了编号、页码和类型标记", clipped.startswith("[1] (第 1 页 · 正文)"))

    many = [block(i, "正文" * 2000) for i in range(20)]
    joined = rag._clip(many)
    check("多段时总量受限", len(joined) <= rag.CONTEXT_CHAR_LIMIT + 64)
    check("多段时首段仍在", joined.startswith("[1] (第 1 页 · 正文)"))

    empty = rag._clip([block(0, "")])
    check("全空的正文段落不进上下文", not empty.strip())

    # 图块经常一个字都抽不到。以前这种块会被整段丢掉，模型只能回答「原文没有提及」。
    figure = block(2, "", kind="figure")
    figure_context = rag._clip([figure])
    check("空文字的图块不会被丢掉", figure_context.strip() != "")
    check("图块标出了自己是图", "(第 3 页 · 图)" in figure_context, figure_context)
    check(
        "图块会说明图里没抽出文字",
        "图里的文字没有抽出来" in figure_context,
        figure_context,
    )

    formula = block(3, "Z = f · b / d (1)", kind="formula")
    check("公式块标出了自己的类型", "(第 4 页 · 公式)" in rag._clip([formula]))

    candidates = [
        block(0, "The experiment evaluates mapping accuracy."),
        block(1, "Hand-eye calibration recovers rotation and translation."),
        block(2, "The dataset contains camera and LiDAR recordings."),
    ]
    ranked = rag.rank_blocks(candidates, "How are rotation and translation calibrated?", 2)
    check("关键词检索能把相关段落排在前面", ranked[0]["id"] == "b1")

    # retrieve 的取舍：锚点那一段必须在，全文模式还要再把关键词命中的补进来。
    # 这里用一个假的存储层，只验挑选逻辑本身。
    stored = [
        block(0, "标定流程分三步", order=0, name="n0"),
        block(0, "误差主要来自时间同步", order=1, name="n1"),
        block(0, "", kind="figure", order=2, name="fig"),
        block(0, "相机和激光雷达要外参", order=3, name="n3"),
        block(0, "同步问题是老问题", order=4, name="n4"),
        block(0, "实验结果放在三张表里", order=5, name="n5"),
        block(0, "未来方向是自动标定", order=6, name="n6"),
    ]
    original = rag.db.get_blocks
    rag.db.get_blocks = lambda _doc_id: stored  # type: ignore[assignment]
    try:
        anchored = rag.retrieve("d", "实验结果", "fig")
        check("带锚点时一定带上锚点那一段", any(item["id"] == "fig" for item in anchored))
        check(
            "带锚点时还按关键词补全篇",
            any("实验结果" in item["text"] for item in anchored),
            str([item["id"] for item in anchored]),
        )
        check(
            "锚点前后的正文排在检索结果前面",
            [item["id"] for item in anchored[:5]] == ["n0", "n1", "fig", "n3", "n4"],
            str([item["id"] for item in anchored]),
        )

        plain = rag.retrieve("d", "实验结果", None)
        check("整篇提问就纯靠检索", all(item["id"] != "fig" for item in plain))
    finally:
        rag.db.get_blocks = original  # type: ignore[assignment]

    print("\n检索层自检通过")


if __name__ == "__main__":
    main()

