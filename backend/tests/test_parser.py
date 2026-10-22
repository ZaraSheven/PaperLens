"""解析器自检：验证分栏阅读顺序、坐标范围，以及主键的稳定性。

直接运行：.venv\\Scripts\\python.exe backend\\tests\\test_parser.py
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import parser  # noqa: E402

DOC_ID = "0123456789abcdef"
WIDTH, HEIGHT = 612, 792
COLUMN_LEFT = 60
COLUMN_RIGHT = 330


def build_two_column_pdf(path: Path) -> None:
    """做一页双栏论文：顶部通栏标题，下面左右各两段正文。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    page.insert_text((60, 60), "A Full Width Title Spanning Both Columns", fontsize=16)

    for index, text in enumerate(["L1 first left paragraph", "L2 second left paragraph"]):
        page.insert_text((COLUMN_LEFT, 150 + index * 50), text, fontsize=11)
    for index, text in enumerate(["R1 first right paragraph", "R2 second right paragraph"]):
        page.insert_text((COLUMN_RIGHT, 150 + index * 50), text, fontsize=11)

    doc.save(path)
    doc.close()


def build_plain_two_column_pdf(path: Path) -> None:
    """没有通栏标题的纯双栏页：只有栏间距，没有别的干扰。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    for index, text in enumerate(["Left one", "Left two", "Left three"]):
        page.insert_text((COLUMN_LEFT, 100 + index * 50), text, fontsize=11)
    for index, text in enumerate(["Right one", "Right two", "Right three"]):
        page.insert_text((COLUMN_RIGHT, 100 + index * 50), text, fontsize=11)
    doc.save(path)
    doc.close()


def build_single_column_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    for index in range(3):
        page.insert_text((60, 100 + index * 100), f"Single column paragraph {index}", fontsize=11)
    doc.save(path)
    doc.close()


def build_hyphenated_pdf(path: Path) -> None:
    """模拟论文排版：一个单词被行末连字符拆成两行。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    for index, text in enumerate(
        [
            "The simula-",
            "tion and develop-",
            "ment methods. state-",
            "of-the-art, real-",
            "world, and Li-",
            "DAR sensor.",
        ]
    ):
        page.insert_text((60, 100 + index * 12), text, fontsize=11)
    doc.save(path)
    doc.close()


def build_numbered_list_pdf(path: Path) -> None:
    """编号列表的每一项都必须单独成块，续行不能串到下一项。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    lines = [
        "The contributions of this study are as follows:",
        "1. First item starts here and",
        "continues on the next line.",
        "2. Second item starts here and",
        "continues on the next line too.",
    ]
    for index, text in enumerate(lines):
        page.insert_text((60, 100 + index * 12), text, fontsize=11)
    page.insert_text((60, 190), "After the list, a normal paragraph.", fontsize=11)
    doc.save(path)
    doc.close()


def build_ruled_table_pdf(path: Path) -> None:
    """只有横线、没有竖线的数据表，应该整张按图片处理。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    page.insert_text((60, 80), "Table 1. Calibration error.", fontsize=11)
    for y in (100, 160, 220, 280, 340):
        page.draw_line(pymupdf.Point(60, y), pymupdf.Point(500, y), color=(0, 0, 0))
    for row, (method, error) in enumerate(
        [("Method", "Error"), ("Ours", "0.12"), ("Blam", "0.31"), ("ICP", "0.48")]
    ):
        y = 150 + row * 60
        page.insert_text((65, y), method, fontsize=9)
        page.insert_text((300, y), error, fontsize=9)
    doc.save(path)
    doc.close()


def build_paged_pdf_with_header(path: Path, page_count: int = 4) -> None:
    """多页文献：每页顶部一行重复页眉（只有页码不同），底部一行页码。"""
    doc = pymupdf.open()
    for index in range(page_count):
        page = doc.new_page(width=WIDTH, height=HEIGHT)
        page.insert_text((60, 50), f"Journal 2019, 12, 345 {index + 1} of {page_count}", fontsize=9)
        if index == 0:
            page.insert_text((60, 70), "A Unique Title On The First Page Only", fontsize=12)
        page.insert_text((60, 120), f"Body paragraph on page {index + 1}", fontsize=11)
        page.insert_text((60, 300), f"Second body paragraph on page {index + 1}", fontsize=11)
        page.insert_text((300, 760), f"{index + 1}", fontsize=9)
    doc.save(path)
    doc.close()


def build_pdf_with_image(path: Path) -> None:
    """一页带插图的文档：插图应当成为一个独立的块。"""
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80))
    pixmap.set_rect(pixmap.irect, (200, 60, 60))
    page.insert_image(pymupdf.Rect(120, 120, 420, 320), pixmap=pixmap)
    page.insert_text((60, 400), "Body text below the figure", fontsize=11)
    doc.save(path)
    doc.close()


def build_vector_figure_pdf(path: Path) -> None:
    """一整页矢量流程图：图形框加一堆短标签。

    这些标签是在图纸里做标注用的，不应该变成几十个独立的可点段落。
    """
    doc = pymupdf.open()
    page = doc.new_page(width=WIDTH, height=HEIGHT)
    for row in range(12):
        top = 80 + row * 40
        page.draw_rect(pymupdf.Rect(80, top, 240, top + 26), color=(0, 0, 0), width=0.8)
        page.draw_line(pymupdf.Point(240, top + 13), pymupdf.Point(300, top + 13))
        page.draw_rect(pymupdf.Rect(300, top, 460, top + 26), color=(0, 0, 0), width=0.8)
        # 行与行之间要有连线，真实的流程图就是这样连起来的。
        if row < 11:
            page.draw_line(pymupdf.Point(160, top + 26), pymupdf.Point(160, top + 40))
            page.draw_line(pymupdf.Point(380, top + 26), pymupdf.Point(380, top + 40))
        page.insert_text((90, top + 17), f"3x3 conv, {row}", fontsize=8)
        page.insert_text((310, top + 17), f"layer {row}", fontsize=8)
    page.insert_text((80, 640), "Body paragraph after the figure", fontsize=11)
    doc.save(path)
    doc.close()


def check(label: str, condition: bool, extra: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} {extra}")
    print(f"  通过  {label}")


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)

        two_col = temp_dir / "two.pdf"
        build_two_column_pdf(two_col)
        blocks, meta = parser.extract_blocks(str(two_col), DOC_ID)

        texts = [b["text"] for b in blocks]
        print("双栏阅读顺序：")
        for text in texts:
            print(f"  {text}")

        check("标题在最前", texts[0].startswith("A Full Width Title"))
        check("先读完左栏", texts[1].startswith("L1") and texts[2].startswith("L2"))
        check("再读右栏", texts[3].startswith("R1") and texts[4].startswith("R2"))
        check("页数正确", meta["page_count"] == 1)

        for block in blocks:
            inside = all(0.0 <= block[key] <= 1.0 for key in ("x0", "y0", "x1", "y1"))
            check(f"坐标归一化 {block['text'][:18]}", inside)
            check(f"顺序号连续 {block['order_index']}", isinstance(block["order_index"], int))

        again, _ = parser.extract_blocks(str(two_col), DOC_ID)
        check("重复解析主键一致", [b["id"] for b in blocks] == [b["id"] for b in again])

        other, _ = parser.extract_blocks(str(two_col), "fedcba9876543210")
        check(
            "同一份内容换个文档编号，主键必须不同",
            not ({b["id"] for b in blocks} & {b["id"] for b in other}),
        )

        plain = temp_dir / "plain.pdf"
        build_plain_two_column_pdf(plain)
        plain_texts = [b["text"] for b in parser.extract_blocks(str(plain), DOC_ID)[0]]
        print(f"纯双栏阅读顺序：{plain_texts}")
        check(
            "纯双栏先读完整栏",
            plain_texts
            == ["Left one", "Left two", "Left three", "Right one", "Right two", "Right three"],
        )

        single = temp_dir / "single.pdf"
        build_single_column_pdf(single)
        single_blocks, _ = parser.extract_blocks(str(single), DOC_ID)
        order = [b["text"] for b in single_blocks]
        check("单栏按上下顺序", order == sorted(order, key=lambda t: t))

        hyphenated = temp_dir / "hyphenated.pdf"
        build_hyphenated_pdf(hyphenated)
        hyphenated_text = " ".join(
            b["text"] for b in parser.extract_blocks(str(hyphenated), DOC_ID)[0]
        )
        check(
            "行末断词会还原成完整单词",
            "simulation and development" in hyphenated_text,
            hyphenated_text,
        )
        check(
            "原有连字符连接词不会被误删",
            "state-of-the-art, real-world" in hyphenated_text,
            hyphenated_text,
        )
        check(
            "缩写被断行时也会拼回",
            "and LiDAR sensor" in hyphenated_text,
            hyphenated_text,
        )
        check(
            "断词位置不会留下连字符加空格",
            "simula- tion" not in hyphenated_text and "develop- ment" not in hyphenated_text,
            hyphenated_text,
        )
        repaired = parser._repair_hyphen_gaps(
            "intrinsic param- eter, Inter- national, feature- and decision-level"
        )
        check(
            "同一视觉行里误补的空格也会修掉",
            repaired == "intrinsic parameter, International, feature- and decision-level",
            repaired,
        )

        numbered = temp_dir / "numbered-list.pdf"
        build_numbered_list_pdf(numbered)
        numbered_texts = [
            b["text"] for b in parser.extract_blocks(str(numbered), DOC_ID)[0]
        ]
        print(f"编号列表分块：{numbered_texts}")
        check(
            "编号列表每一项单独成块",
            sum(1 for text in numbered_texts if re.match(r"^\d+\.", text)) == 2,
            str(numbered_texts),
        )
        check(
            "编号列表续行留在本项",
            any(text.startswith("1. First item") and "continues on the next line." in text for text in numbered_texts),
            str(numbered_texts),
        )
        check(
            "一块不会同时包含两个编号",
            not any("1." in text and "2." in text for text in numbered_texts),
            str(numbered_texts),
        )
        check(
            "列表结束后普通段落重新起块",
            any(text.startswith("After the list") for text in numbered_texts),
            str(numbered_texts),
        )

        table_pdf = temp_dir / "ruled-table.pdf"
        build_ruled_table_pdf(table_pdf)
        table_blocks, _ = parser.extract_blocks(str(table_pdf), DOC_ID)
        tables = [block for block in table_blocks if block["kind"] == "table"]
        check("无竖线表格被收成表格块", len(tables) == 1, str(table_blocks))
        check(
            "表格标题和单元格文字保留在表格块里",
            bool(tables)
            and "Table 1." in tables[0]["text"]
            and "Ours" in tables[0]["text"],
            tables[0]["text"] if tables else "",
        )

        paged = temp_dir / "paged.pdf"
        build_paged_pdf_with_header(paged)
        paged_texts = [b["text"] for b in parser.extract_blocks(str(paged), DOC_ID)[0]]
        print(f"多页去页眉结果：{paged_texts}")
        check("重复页眉被去掉", not any(t.startswith("Journal 2019") for t in paged_texts))
        check("只出现一次的标题保留", any(t.startswith("A Unique Title") for t in paged_texts))
        check("正文全部保留", sum(1 for t in paged_texts if "Body paragraph" in t) == 4)

        check("乱码块被识别为无内容", not parser._has_readable_content("\x01\x02\x03\x04"))
        check("正常文字被识别为有内容", parser._has_readable_content("Robust GICP SLAM"))
        check("中文被识别为有内容", parser._has_readable_content("地下矿山三维激光"))

        illustrated = temp_dir / "illustrated.pdf"
        build_pdf_with_image(illustrated)
        illustrated_blocks, _ = parser.extract_blocks(str(illustrated), DOC_ID)
        images = [b for b in illustrated_blocks if b["kind"] == "figure"]
        check("插图被抽成一个图表块", len(images) == 1, str(len(images)))
        if images:
            image = images[0]
            near = abs(image["x0"] * WIDTH - 120) < 12 and abs(image["y1"] * HEIGHT - 320) < 12
            check("图表块坐标落在插图位置", near, f"x0={image['x0']:.3f} y1={image['y1']:.3f}")
        check(
            "图表块排在正文之前",
            any(b["kind"] == "figure" for b in illustrated_blocks[:1]),
            str([b["kind"] for b in illustrated_blocks]),
        )
        check("插图下方的正文保留", any("Body text below" in b["text"] for b in illustrated_blocks))

        check("TeX 数学字体被认出来", bool(parser._MATH_FONT.search("CMR10")))
        check("Cambria Math 被认出来", bool(parser._MATH_FONT.search("CambriaMath")))
        check("正文衬线字体不算数学字体", not parser._MATH_FONT.search("URWPalladioL-Roma"))
        check(
            "数学字体画出的 ff 连字不算公式",
            not parser._math_span(
                {
                    "math": True,
                    "text": "ff",
                    "x0": 0,
                    "y0": 0,
                    "x1": 5,
                    "y1": 10,
                    "size": 10,
                }
            ),
        )
        check(
            "真正的数学符号仍然算公式",
            parser._math_span(
                {
                    "math": True,
                    "text": "∆",
                    "x0": 0,
                    "y0": 0,
                    "x1": 5,
                    "y1": 10,
                    "size": 10,
                }
            ),
        )
        check(
            "带上下标的行碎片仍算同一视觉行",
            parser._same_visual_line(
                {
                    "x0": 70,
                    "y0": 100,
                    "x1": 280,
                    "y1": 112,
                    "size": 10,
                    "text": "正文",
                },
                {
                    "x0": 283,
                    "y0": 105,
                    "x1": 330,
                    "y1": 115,
                    "size": 10,
                    "text": "公式",
                },
            ),
        )
        check(
            "普通相邻两行不会被误并",
            not parser._same_visual_line(
                {
                    "x0": 70,
                    "y0": 100,
                    "x1": 300,
                    "y1": 111,
                    "size": 10,
                    "text": "上一行",
                },
                {
                    "x0": 70,
                    "y0": 112,
                    "x1": 300,
                    "y1": 123,
                    "size": 10,
                    "text": "下一行",
                },
            ),
        )

        inline_parts = [
            {
                "spans": [
                    {
                        "x0": 70,
                        "y0": 100,
                        "x1": 150,
                        "y1": 111,
                        "text": "结果是 ",
                        "size": 10,
                        "math": False,
                    },
                    {
                        "x0": 150,
                        "y0": 98,
                        "x1": 168,
                        "y1": 110,
                        "text": "x2",
                        "size": 10,
                        "math": True,
                    },
                    {
                        "x0": 169,
                        "y0": 100,
                        "x1": 230,
                        "y1": 111,
                        "text": "，继续阅读。",
                        "size": 10,
                        "math": False,
                    },
                ]
            }
        ]
        inline_segments = parser._line_segments(inline_parts)
        check(
            "行内公式从正文里单独切出来",
            [segment["kind"] for segment in inline_segments] == ["text", "math", "text"],
            str(inline_segments),
        )
        check(
            "行内公式保留了原页面坐标",
            inline_segments[1]["x0"] == 150 and inline_segments[1]["x1"] == 168,
            str(inline_segments[1]),
        )

        vector = temp_dir / "vector-figure.pdf"
        build_vector_figure_pdf(vector)
        vector_blocks, _ = parser.extract_blocks(str(vector), DOC_ID)
        figures = [b for b in vector_blocks if b["kind"] == "figure"]
        check("矢量图的标签合成一个图表块", len(figures) == 1, str([b["kind"] for b in vector_blocks]))
        check("图后面那段正文仍然单独成段", len(vector_blocks) == 2, str(len(vector_blocks)))
        check(
            "图表块的文字保留了标签内容",
            bool(figures) and "3x3 conv" in figures[0]["text"],
            figures[0]["text"][:60] if figures else "",
        )
        check(
            "图后面的正文没被并进图表块",
            any(
                b["kind"] == "text" and b["text"].startswith("Body paragraph")
                for b in vector_blocks
            ),
        )

    print("\n解析器自检通过")


if __name__ == "__main__":
    main()

