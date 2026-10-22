"""PDF 解析：把每页抽成带归一化坐标的段落、公式块与图片区域，并排出阅读顺序。

这一层有四件事最关键：

1. **段落重建**。学术 PDF 里行内公式（尤其是上下标）会让 PDF 自己的「块」在公式处断开，
   一句话被切成七八个互相重叠的碎片。所以这里不信 PDF 的块结构，改成按行重组：
   先把同一视觉行的碎片拼成一行，再把连续的行按行距、缩进、字号归并成段落。
2. **公式块**。独立成行的公式由一堆零散符号拼成，按行归并只会得到更碎的东西。
   这里沿"小块紧挨着谁"把它们粘成一整块，并按字符用到的字体判断它是不是公式。
   公式块的文字是抽不准的，前端会改用它所在页面的截图，让用户直接看到原式。
3. **图片区域**。图形必须作为独立的块保留下来，否则图上是一片死区，图注也会和正文错位。
   同一张图被重复绘制多次时（MDPI 的论文就会这样）要合并成一个区域。
4. **阅读顺序**。用 XY-cut 递归切分，处理双栏、通栏标题和图文的混排。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any

import pymupdf
import pdfplumber
import wordninja

# 垂直分隔至少要有页面宽度的这个比例才算栏间距，避免行末参差被当成栏间距。
MIN_VERTICAL_GAP = 0.02
# 水平分隔至少要有页面高度的这个比例才算段落间距。
MIN_HORIZONTAL_GAP = 0.012
# 递归深度上限，防止病态输入把切分拖成死循环。
MAX_DEPTH = 12
# 页眉页脚判定：位于页面顶部或底部这个比例的范围内。
TOP_BAND = 0.10
BOTTOM_BAND = 0.90
# 页眉页脚要在这么多比例的页面上重复出现才算。
REPEAT_RATIO = 0.5
# 小于这个尺寸的图形当作图标、装饰线，不单独成块。
MIN_IMAGE_SIDE = 12.0
# 两块图形重叠超过较小那块的这个比例，就认为是同一张图被画了两次。
IMAGE_MERGE_RATIO = 0.5
# 归并成同一段落时允许的最大行距，按行高折算。
MAX_LINE_GAP_RATIO = 0.8
# 同一视觉行的碎片至少要纵向重叠这么多。带上下标的行会把行框拉高，
# 相邻碎片常常只重叠四成左右；阈值取 0.5 会把它们拆成两行，最后切出半句话。
MIN_VISUAL_OVERLAP_RATIO = 0.3
# 首行缩进超过这个比例就认为另起一段。
INDENT_RATIO = 0.4
# 编号列表项结束后常见“同一悬挂缩进重新起段”，靠更大的行距识别。
LIST_ITEM_GAP_RATIO = 0.5
# 宽度不到页面这个比例的块，视为被公式打散的碎片。
SHORT_BLOCK_RATIO = 0.55
# 成片的矢量图形至少要这么多，才算一张图。
MIN_FIGURE_SHAPES = 8
# 如果这片区域里压着文字，要求更密的图形才认。真正的图（流程图、热力图、格线表格）
# 动辄上百个图形；而给正文套个虚线框只有几个到十几个，不该把正文吞成图片。
MIN_FIGURE_SHAPES_WITH_TEXT = 24
# 相邻这么近的矢量图形算同一片：图里的方框、箭头、连线本来就是挨着的。
# 取 14 是实测出来的：ResNet 那张整版架构图的方框间距最大就到这个量级，
# 半径再小它会被切成三片，图里一半的标注会漏到外面变成独立段落。
FIGURE_CLUSTER_MARGIN = 14.0
# 一片矢量图形要盖住页面这个面积比例才算一张图。
MIN_VECTOR_FIGURE_AREA = 0.05
# 小块之间上下堆叠时，间距超过字号这个比例就不算挨着，按字号折算。
GLUE_STACK_RATIO = 0.4
# 数学字体占比超过这个数就认为这一块是公式。
# 实测这份论文的公式块占比在 0.12~0.38，正文段落最高只到 0.06，阈值取在中间很干净。
MATH_RATIO = 0.10
# 占比很高的直接算公式，不必再看词数。
MATH_RATIO_STRONG = 0.20
# 公式里不会有太多完整单词。图注虽然也带数学符号，但它是整句话，靠这个把它挡在外面。
MAX_FORMULA_WORDS = 12

_WS = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
_WORD = re.compile(r"[A-Za-z]{2,}")
_LIST_START = re.compile(r"^(?:\d{1,3}[.)]|\(\d{1,3}\)|[A-Za-z][.)]|[•●▪◦‣·])\s+\S")
_HYPHEN_GAP = re.compile(r"([A-Za-z]+)([-\u2010\u00ad])\s+([A-Za-z]+)")
_TABLE_CAPTION = re.compile(r"^\s*Table\s+(?:\d+|[IVX]+)[.:]\s+\S", re.IGNORECASE)
# 控制字符会混进正文（PDF 里用退格做叠打），留着只会让文字变成乱码。
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 各家的数学字体命名：TeX 的 CM*、Px*、LM*，以及 STIX、Cambria Math、MathType 等。
_MATH_FONT = re.compile(
    r"^(CM[RBSEMX]\d|Rpx|Px[a-z]|LM[A-Z]|LMMI|LMSY|MTMI|MTSY|MTEX)"
    r"|math|symbol|msam|msbm|stix|xits|euclid|asana",
    re.IGNORECASE,
)
# 这些词在 PDF 里通常不是数学字体，但它们是公式的一部分。
_MATH_WORDS = {
    "arccos",
    "arcsin",
    "arctan",
    "argmax",
    "argmin",
    "cos",
    "cosh",
    "det",
    "diag",
    "exp",
    "log",
    "max",
    "min",
    "rank",
    "sin",
    "sinh",
    "sqrt",
    "tan",
    "tanh",
    "trace",
}
_MATH_SYMBOLS = set("=+-−±×÷<>≤≥≈∼∥|()[]{}^_√∑∫∂∇∆δθλμπωσρφτ")
_LIGATURES = {"ﬀ", "ﬁ", "ﬂ", "ﬃ", "ﬄ", "ﬅ", "ﬆ", "ff", "fi", "fl", "ffi", "ffl"}
# 这些结尾几乎总是单词的一部分，不是独立单词；遇到它们一定拼回去。
_WORD_SUFFIXES = {
    "able",
    "al",
    "ally",
    "ance",
    "ed",
    "ence",
    "er",
    "etry",
    "ful",
    "graph",
    "gram",
    "ible",
    "ical",
    "ing",
    "ise",
    "ity",
    "ive",
    "ize",
    "less",
    "ly",
    "ment",
    "ness",
    "ology",
    "or",
    "ous",
    "scope",
    "sion",
    "tion",
}
_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "lines",
    "min_words_vertical": 2,
    "text_x_tolerance": 1,
    "text_y_tolerance": 1,
}
# 表格标题通常紧贴表格上方；留出较宽容差，真正的边界由 pdfplumber 的表格框决定。
TABLE_CAPTION_DISTANCE = 100


def _normalize_text(text: str) -> str:
    cleaned = _CONTROL.sub("", unicodedata.normalize("NFKC", text))
    return _WS.sub(" ", cleaned).strip()


def _has_readable_content(text: str) -> bool:
    """至少要有一个字母或数字。

    PDF 里字体没有正确 ToUnicode 映射时，抽出来是一串控制字符，这类块对读者毫无意义。
    """
    return any(char.isalnum() for char in text)


def _clean_segment_text(text: str) -> str:
    """清理行内片段的控制字符，但保留片段自己的空格。"""
    return unicodedata.normalize("NFKC", _CONTROL.sub("", text))


def _shape(text: str) -> str:
    """把数字抹平，用来比对页眉页脚。

    页眉里的页码每页都不同（"2 of 19"、"3 of 19"），直接比对文本永远匹配不上。
    """
    return _DIGITS.sub("#", text)


# --------------------------------------------------------------------- 行重组

def _raw_fragments(page: pymupdf.Page) -> list[dict[str, Any]]:
    """取出页面上的文字片段。每个片段是 PDF 视角下的一行，可能只是半行。"""
    fragments: list[dict[str, Any]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text_spans = [span for span in line["spans"] if span["text"].strip()]
            if not text_spans:
                continue
            chars = sum(len(span["text"]) for span in text_spans) or 1
            math_chars = sum(
                len(span["text"])
                for span in text_spans
                if _MATH_FONT.search(span["font"])
            )
            x0, y0, x1, y1 = line["bbox"]
            fragments.append(
                {
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "text": "".join(span["text"] for span in line["spans"]),
                    "size": max(span["size"] for span in text_spans),
                    "chars": chars,
                    "math_chars": math_chars,
                    "spans": [
                        {
                            "x0": span["bbox"][0],
                            "y0": span["bbox"][1],
                            "x1": span["bbox"][2],
                            "y1": span["bbox"][3],
                            "text": _clean_segment_text(span["text"]),
                            "size": span["size"],
                            "math": bool(_MATH_FONT.search(span["font"])),
                        }
                        # 空格也是独立 span，必须留着，否则行内片段拼起来会少掉词间空格。
                        for span in line["spans"]
                        if span["text"]
                    ],
                }
            )
    return fragments


def _same_visual_line(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """两段文字是不是同一视觉行被拆开的两截。

    判据是纵向重叠够多、横向又挨得够近。双栏论文左右两栏的行虽然高度相同，
    但中间隔着栏间距，横向距离远，所以不会被误并成一行。
    """
    overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    height = min(a["y1"] - a["y0"], b["y1"] - b["y0"])
    if height <= 0 or overlap < MIN_VISUAL_OVERLAP_RATIO * height:
        return False
    if min(a["x1"], b["x1"]) >= max(a["x0"], b["x0"]):
        return True
    gap = max(a["x0"], b["x0"]) - min(a["x1"], b["x1"])
    return gap <= 1.2 * max(a["size"], b["size"])


def _join_parts(parts: list[dict[str, Any]]) -> str:
    """把同一视觉行的碎片按横向顺序拼起来。

    字号明显更小的碎片多半是上下标，直接接上去；其余情况补一个空格，
    否则两个独立文本段会被焊成一个不存在的词。
    """
    ordered = sorted(parts, key=lambda part: part["x0"])
    text = ordered[0]["text"].strip()
    for previous, current in zip(ordered, ordered[1:]):
        piece = current["text"].strip()
        if not piece:
            continue
        if current["size"] < previous["size"] - 0.5:
            text += piece
        else:
            text += f" {piece}"
    return text.strip()


def _math_span(span: dict[str, Any]) -> bool:
    """这个 span 是不是公式的一部分。"""
    stripped = _WS.sub("", span["text"]).lower()
    if span["math"]:
        # 某些正文 PDF 用 Rpxr 之类的数学字体画连字，别把 "ﬀ" 当成公式。
        if stripped in _LIGATURES:
            return False
        return not (stripped.isalpha() and len(stripped) >= 2 and stripped not in _MATH_WORDS)
    if stripped in _MATH_WORDS:
        return True
    return (
        bool(stripped)
        and len(stripped) <= 4
        and all(char in _MATH_SYMBOLS for char in stripped)
    )


def _line_segments(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把视觉行切成文字片段和行内公式片段。

    公式在 PDF 里经常拆成多个 span，还会和上下标、分数线的行框互相重叠。
    这里按横坐标拼接相邻 span：数学字体、常见函数名，以及被公式包围的片段
    都归到同一个公式里。前端拿公式片段的坐标去原页面裁图，就能把乱码换成原式。
    """
    spans = [
        span
        for part in parts
        for span in part.get("spans", [])
        if span["text"]
    ]
    spans.sort(key=lambda span: (span["x0"], span["y0"], span["x1"]))

    groups: list[dict[str, Any]] = []
    for span in spans:
        is_math = _math_span(span)
        if groups:
            group = groups[-1]
            size = min(group["size"], span["size"])
            gap = span["x0"] - group["x1"]
            overlap = min(group["y1"], span["y1"]) - max(group["y0"], span["y0"])
            plain = _WS.sub("", span["text"])
            plain_math = (
                bool(plain)
                and len(plain) <= 3
                and (
                    all(
                        char.isdigit() or char in _MATH_SYMBOLS or char in ".,"
                        for char in plain
                    )
                    or (len(plain) <= 2 and plain.isalnum())
                )
            )
            inside = (
                span["x0"] >= group["x0"] - 0.5
                and span["x1"] <= group["x1"] + 0.5
            )
            vertical = overlap >= -0.35 * min(
                group["y1"] - group["y0"], span["y1"] - span["y0"]
            )

            if group["kind"] == "math":
                # 分数、根号和上下标经常互相覆盖；只要横向还连着，就继续算同一式。
                if (
                    is_math
                    or inside
                    or (plain_math and gap <= 2.5 * size and vertical)
                ):
                    group["text"] += span["text"]
                    group["x0"] = min(group["x0"], span["x0"])
                    group["y0"] = min(group["y0"], span["y0"])
                    group["x1"] = max(group["x1"], span["x1"])
                    group["y1"] = max(group["y1"], span["y1"])
                    group["size"] = max(group["size"], span["size"])
                    continue
            elif (
                not is_math
                and gap <= 0.7 * size
                and overlap >= MIN_VISUAL_OVERLAP_RATIO
                * min(group["y1"] - group["y0"], span["y1"] - span["y0"])
            ):
                group["text"] += span["text"]
                group["x0"] = min(group["x0"], span["x0"])
                group["y0"] = min(group["y0"], span["y0"])
                group["x1"] = max(group["x1"], span["x1"])
                group["y1"] = max(group["y1"], span["y1"])
                group["size"] = max(group["size"], span["size"])
                continue

        groups.append(
            {
                "kind": "math" if is_math else "text",
                "text": span["text"],
                "x0": span["x0"],
                "y0": span["y0"],
                "x1": span["x1"],
                "y1": span["y1"],
                "size": span["size"],
            }
        )

    # 一个字母、一个连字宽度太小，显示成图片没有意义；留在正文文字里更自然。
    for group in groups:
        if group["kind"] == "math" and group["x1"] - group["x0"] < 3.0:
            group["kind"] = "text"
    return [group for group in groups if group["text"].strip()]


def _absorb(line: dict[str, Any], fragment: dict[str, Any]) -> None:
    line["parts"].append(fragment)
    line["x0"] = min(line["x0"], fragment["x0"])
    line["x1"] = max(line["x1"], fragment["x1"])
    line["y0"] = min(line["y0"], fragment["y0"])
    line["y1"] = max(line["y1"], fragment["y1"])
    line["size"] = max(line["size"], fragment["size"])
    line["chars"] += fragment["chars"]
    line["math_chars"] += fragment["math_chars"]


def _merge_lines_once(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: (item["y0"], item["x0"])):
        for kept in reversed(merged[-8:]):
            if _same_visual_line(kept, line):
                for part in line["parts"]:
                    _absorb(kept, part)
                break
        else:
            merged.append(line)
    return merged


def _visual_lines(page: pymupdf.Page) -> list[dict[str, Any]]:
    """页面上的视觉行。

    反复归并到不再变化为止。碎片之间常是链式相邻的（C 同时压住 A 和 B），
    只往回看一步会把链走断，同一行被拆成好几段。
    """
    lines = [
        {"kind": "line", **fragment, "parts": [fragment]}
        for fragment in _raw_fragments(page)
    ]
    while True:
        merged = _merge_lines_once(lines)
        if len(merged) == len(lines):
            lines = merged
            break
        lines = merged

    for line in lines:
        line["text"] = _join_parts(line["parts"])
        line["segments"] = _line_segments(line["parts"])
    return [line for line in lines if _has_readable_content(line["text"])]


# ------------------------------------------------------------------ 图形区域

def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    width = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    height = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min(
        (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]),
        (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]),
    )
    return (width * height) / smaller if smaller > 0 else 0.0


def _image_regions(page: pymupdf.Page) -> list[dict[str, Any]]:
    """页面上的图形区域。

    同一张图在同一页被绘制多次时（这份 MDPI 论文每张图都画了两遍，位置还差十几点），
    合并成一块，否则图上会叠出两个可点区域。
    """
    regions: list[dict[str, Any]] = []
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        box = {
            "kind": "figure",
            "x0": min(x0, x1),
            "y0": min(y0, y1),
            "x1": max(x0, x1),
            "y1": max(y0, y1),
            "text": "",
            "size": 0.0,
            "chars": 0,
            "math_chars": 0,
        }
        if box["x1"] - box["x0"] < MIN_IMAGE_SIDE or box["y1"] - box["y0"] < MIN_IMAGE_SIDE:
            continue
        for kept in regions:
            if _overlap_ratio(kept, box) >= IMAGE_MERGE_RATIO:
                kept["x0"] = min(kept["x0"], box["x0"])
                kept["y0"] = min(kept["y0"], box["y0"])
                kept["x1"] = max(kept["x1"], box["x1"])
                kept["y1"] = max(kept["y1"], box["y1"])
                break
        else:
            regions.append(box)
    return regions


def _cluster_rects(rects: list[pymupdf.Rect]) -> list[tuple[int, pymupdf.Rect]]:
    """把挨在一起的图形框并成一片，返回 (图形数, 包围盒)。"""
    parent = list(range(len(rects)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    grown = [
        pymupdf.Rect(
            rect.x0 - FIGURE_CLUSTER_MARGIN,
            rect.y0 - FIGURE_CLUSTER_MARGIN,
            rect.x1 + FIGURE_CLUSTER_MARGIN,
            rect.y1 + FIGURE_CLUSTER_MARGIN,
        )
        for rect in rects
    ]
    # 按左边界扫一遍，只跟横向可能相交的比。整页上千个图形时，两两比较太慢。
    order = sorted(range(len(grown)), key=lambda index: grown[index].x0)
    for position, left in enumerate(order):
        for right in order[position + 1 :]:
            if grown[right].x0 > grown[left].x1:
                break
            if grown[left].intersects(grown[right]):
                root_left, root_right = find(left), find(right)
                if root_left != root_right:
                    parent[root_right] = root_left

    groups: dict[int, list[pymupdf.Rect]] = {}
    for index, rect in enumerate(rects):
        groups.setdefault(find(index), []).append(rect)

    clustered: list[tuple[int, pymupdf.Rect]] = []
    for group in groups.values():
        box = group[0]
        for rect in group[1:]:
            box |= rect
        clustered.append((len(group), box))
    return sorted(clustered, key=lambda item: item[0], reverse=True)


def _drawing_regions(
    page: pymupdf.Page,
    lines: list[dict[str, Any]],
    width: float,
    height: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把成片的矢量图形收成图表块，返回 (图表块, 剩下没被收走的文字行)。

    流程图、热力图、用格线画的表格都是矢量图形。图里的标注、被可视化的句子属于这张图，
    不该各自变成可点的小段——实测一整页架构图能散成 111 段，每段都是 "3x3 conv, 64"
    这种碎片。这里把图形聚成片，连同片内的文字一起收成一个块。

    判据靠图形密度：整页散落几个装饰框、给正文套一层虚线框，都达不到阈值。
    """
    rects = [shape["rect"] for shape in page.get_drawings()]
    if not rects:
        return [], lines

    page_area = width * height
    regions: list[dict[str, Any]] = []
    boxes: list[pymupdf.Rect] = []
    for count, box in _cluster_rects(rects):
        if box.get_area() < MIN_VECTOR_FIGURE_AREA * page_area:
            continue
        inside = [line for line in lines if _centre_inside(line, box)]
        needed = MIN_FIGURE_SHAPES_WITH_TEXT if inside else MIN_FIGURE_SHAPES
        if count < needed:
            continue
        boxes.append(box)
        regions.append(
            {
                "kind": "figure",
                "x0": max(0.0, box.x0),
                "y0": max(0.0, box.y0),
                "x1": min(width, box.x1),
                "y1": min(height, box.y1),
                # 图里的文字照样留着：表格的格子、被可视化的句子都是有内容价值的，
                # 翻译和问答用得着。界面上仍然优先显示原图。
                "text": " ".join(line["text"] for line in inside),
                "size": max((line["size"] for line in inside), default=0.0),
                "chars": sum(line["chars"] for line in inside),
                "math_chars": sum(line["math_chars"] for line in inside),
            }
        )

    remaining = [
        line for line in lines if not any(_centre_inside(line, box) for box in boxes)
    ]
    return regions, remaining


def _centre_inside(line: dict[str, Any], box: pymupdf.Rect) -> bool:
    return (
        box.x0 <= (line["x0"] + line["x1"]) / 2 <= box.x1
        and box.y0 <= (line["y0"] + line["y1"]) / 2 <= box.y1
    )


def _table_regions(
    plumber_page: Any,
    lines: list[dict[str, Any]],
    width: float,
    height: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把带 "Table N" 标题的数据表收成整张原图块。

    论文里的表格格式差异很大：有的只有横线，有的完全没有格线。
    这里只在页面确实出现 Table 标题时调用 pdfplumber，并要求候选区域与标题对齐，
    避免把正文段落、作者信息或参考文献误当成表格。
    """
    captions = [line for line in lines if _TABLE_CAPTION.match(line["text"].strip())]
    if not captions:
        return [], lines

    try:
        tables = plumber_page.find_tables(_TABLE_SETTINGS)
    except Exception:
        return [], lines

    regions: list[dict[str, Any]] = []
    boxes: list[pymupdf.Rect] = []
    page_area = width * height
    for table in tables:
        bbox = pymupdf.Rect(table.bbox)
        caption = next(
            (
                line
                for line in captions
                if bbox.y0 - TABLE_CAPTION_DISTANCE <= line["y0"] <= bbox.y1 + 10
            ),
            None,
        )
        if caption is None:
            continue

        data = table.extract()
        filled_rows = [row for row in data if any(cell and str(cell).strip() for cell in row)]
        max_cols = max((len(row) for row in filled_rows), default=0)
        if len(filled_rows) < 2 and max_cols < 4:
            continue
        if bbox.get_area() < 0.04 * page_area:
            continue

        # 标题一定属于表格图片的一部分；识别到的框如果从标题上方开始，就把它裁掉。
        caption_top = max(0.0, caption["y0"] - 4)
        top = caption_top if bbox.y0 < caption["y0"] - 20 else min(bbox.y0, caption_top)
        box = pymupdf.Rect(
            max(0.0, bbox.x0),
            top,
            min(width, bbox.x1),
            min(height, bbox.y1),
        )
        if box.x1 <= box.x0 or box.y1 <= box.y0:
            continue
        boxes.append(box)
        inside = [line for line in lines if _centre_inside(line, box)]
        regions.append(
            {
                "kind": "table",
                "x0": box.x0,
                "y0": box.y0,
                "x1": box.x1,
                "y1": box.y1,
                "text": " ".join(line["text"] for line in inside),
                "size": max((line["size"] for line in inside), default=0.0),
                "chars": sum(line["chars"] for line in inside),
                "math_chars": sum(line["math_chars"] for line in inside),
            }
        )

    remaining = [
        line for line in lines if not any(_centre_inside(line, box) for box in boxes)
    ]
    return regions, remaining


# ------------------------------------------------------------------ 阅读顺序

def _widest_gap(
    intervals: list[tuple[float, float]], low: float, high: float
) -> tuple[float, float | None]:
    """在 [low, high] 内找最宽的未被覆盖空隙，返回 (宽度, 中心)。"""
    clipped = sorted(
        (max(start, low), min(end, high))
        for start, end in intervals
        if min(end, high) > max(start, low)
    )

    best, centre, cursor = 0.0, None, low
    for start, end in clipped:
        if start - cursor > best:
            best, centre = start - cursor, (cursor + start) / 2
        cursor = max(cursor, end)
    if high - cursor > best:
        best, centre = high - cursor, (cursor + high) / 2
    return best, centre


def _xy_cut(
    items: list[dict[str, Any]], page: tuple[float, float], depth: int = 0
) -> list[dict[str, Any]]:
    """递归切分：按最宽的空白把区域拆开，拆不动了就按位置输出。

    每次都用子集自身的包围盒当区域，不把区域边界从上一次切分继承下来。继承边界会把
    「上一刀到第一块之间的空白」当成可切分的位置，这类假空白经常比真正的栏间距还宽。
    """
    by_position = lambda: sorted(items, key=lambda b: (b["y0"], b["x0"]))  # noqa: E731
    if len(items) <= 1 or depth >= MAX_DEPTH:
        return by_position()

    low = (min(b["x0"] for b in items), min(b["y0"] for b in items))
    high = (max(b["x1"] for b in items), max(b["y1"] for b in items))

    vertical, vertical_at = _widest_gap([(b["x0"], b["x1"]) for b in items], low[0], high[0])
    horizontal, horizontal_at = _widest_gap([(b["y0"], b["y1"]) for b in items], low[1], high[1])

    # 两个方向的空白用同一把尺子（点）比较大小，各自只要过自己的下限就有资格切开。
    can_split_vertical = vertical >= MIN_VERTICAL_GAP * page[0] and vertical_at is not None
    can_split_horizontal = horizontal >= MIN_HORIZONTAL_GAP * page[1] and horizontal_at is not None
    if not can_split_vertical and not can_split_horizontal:
        return by_position()

    if can_split_vertical and (not can_split_horizontal or vertical >= horizontal):
        left = [b for b in items if b["x1"] <= vertical_at]
        right = [b for b in items if b["x0"] >= vertical_at]
        if not left or not right:
            return by_position()
        return _xy_cut(left, page, depth + 1) + _xy_cut(right, page, depth + 1)

    top = [b for b in items if b["y1"] <= horizontal_at]
    bottom = [b for b in items if b["y0"] >= horizontal_at]
    if not top or not bottom:
        return by_position()
    return _xy_cut(top, page, depth + 1) + _xy_cut(bottom, page, depth + 1)


# ------------------------------------------------------------------ 段落归并

def _starts_new_paragraph(paragraph: dict[str, Any], line: dict[str, Any]) -> bool:
    """这一行是不是另起了一段。"""
    last = paragraph["last"]
    size = last["size"]

    if _LIST_START.match(line["text"].strip()):
        return True
    gap = line["y0"] - last["y1"]
    if gap > MAX_LINE_GAP_RATIO * size or gap < -0.5 * size:
        return True
    if abs(line["size"] - size) > 0.8:
        return True
    # 编号/项目符号后的续行通常会悬挂缩进，不能按首行缩进另起一段。
    if paragraph.get("list_item"):
        return gap > LIST_ITEM_GAP_RATIO * size
    # 首行缩进：比本段左边距明显靠右，说明是新一段的第一行。
    # 反过来（比左边距更靠左）是缩进段落的后续行，仍属同一段。
    return line["x0"] > paragraph["left"] + INDENT_RATIO * size


def _new_paragraph(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "text",
        "x0": line["x0"],
        "y0": line["y0"],
        "x1": line["x1"],
        "y1": line["y1"],
        "size": line["size"],
        "left": line["x0"],
        "text": line["text"],
        "chars": line["chars"],
        "math_chars": line["math_chars"],
        "segments": [dict(segment) for segment in line.get("segments", [])],
        "list_item": bool(_LIST_START.match(line["text"].strip())),
        "last": line,
    }


def _is_word_piece(token: str) -> bool:
    """wordninja 认为 token 本身就是一个完整单词时返回真。"""
    lowered = token.lower()
    parts = wordninja.split(lowered)
    return len(parts) == 1 and parts[0] == lowered


def _line_join_mode(previous: str, following: str) -> str:
    """判断上一行末尾和下一行开头该怎么接。

    返回 remove 表示去掉行末连字符直接拼；keep 表示保留连字符但不补空格；
    space 表示这是普通换行，补一个空格。
    """
    head = previous.rstrip()
    tail = following.lstrip()
    if not head or not tail or head[-1] not in "-\u2010\u00ad":
        return "space"

    prefix_match = re.search(r"([A-Za-z]+)$", head[:-1])
    suffix_match = re.match(r"([A-Za-z]+)", tail)
    if not prefix_match or not suffix_match:
        return "remove"

    prefix = prefix_match.group(1)
    suffix = suffix_match.group(1)
    candidate = f"{prefix}{suffix}".lower()
    suffix_lower = suffix.lower()

    if suffix_lower in _WORD_SUFFIXES:
        return "remove"
    # "feature- and decision-level" 里的空格是有意义的，不能拼成 feature-and。
    if suffix_lower in {"and", "or"}:
        return "space"
    # LiDAR 这类缩写被排成 "Li-" + "DAR" 时，连字符是排版产物。
    if suffix.isupper() and len(suffix) <= 5:
        return "remove"

    parts = wordninja.split(candidate)
    if len(parts) == 1 and parts[0] == candidate:
        return "remove"
    if _is_word_piece(prefix) and _is_word_piece(suffix):
        return "keep"
    return "remove"


def _repair_hyphen_gaps(text: str) -> str:
    """修掉同一个视觉行被拆开后误补的空格。"""

    def replace(match: re.Match[str]) -> str:
        prefix, hyphen, suffix = match.groups()
        mode = _line_join_mode(f"{prefix}{hyphen}", suffix)
        if mode == "remove":
            return f"{prefix}{suffix}"
        if mode == "keep":
            return f"{prefix}{hyphen}{suffix}"
        return match.group(0)

    return _HYPHEN_GAP.sub(replace, text)


def _extend_paragraph(paragraph: dict[str, Any], line: dict[str, Any]) -> None:
    segments = paragraph.setdefault("segments", [])
    mode = _line_join_mode(paragraph["text"], line["text"])
    if mode == "remove":
        # "simula-" + "tion" 要还原成 "simulation"，不能留成 "simula- tion"。
        paragraph["text"] = paragraph["text"].rstrip()[:-1] + line["text"].lstrip()
        if segments and segments[-1]["kind"] == "text":
            segments[-1]["text"] = segments[-1]["text"].rstrip()[:-1]
    elif mode == "keep":
        # "state-" + "of-the-art" 保留连字符，但不能留下换行空格。
        paragraph["text"] = paragraph["text"].rstrip() + line["text"].lstrip()
        if segments and segments[-1]["kind"] == "text":
            segments[-1]["text"] = segments[-1]["text"].rstrip()
    else:
        paragraph["text"] += f" {line['text']}"
        if segments and segments[-1]["kind"] == "text":
            segments[-1]["text"] += " "
        else:
            segments.append({"kind": "text", "text": " "})
    segments.extend(dict(segment) for segment in line.get("segments", []))
    paragraph["x0"] = min(paragraph["x0"], line["x0"])
    paragraph["y0"] = min(paragraph["y0"], line["y0"])
    paragraph["x1"] = max(paragraph["x1"], line["x1"])
    paragraph["y1"] = max(paragraph["y1"], line["y1"])
    paragraph["left"] = min(paragraph["left"], line["x0"])
    paragraph["chars"] += line["chars"]
    paragraph["math_chars"] += line["math_chars"]
    paragraph["last"] = line


def _group_paragraphs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把排好序的行与图片归并成块。图片各自成块，文字行按段落归并。"""
    blocks: list[dict[str, Any]] = []
    paragraph: dict[str, Any] | None = None

    for item in items:
        if item["kind"] in {"figure", "table"}:
            if paragraph:
                blocks.append(paragraph)
                paragraph = None
            blocks.append(dict(item))
            continue

        if paragraph is None or _starts_new_paragraph(paragraph, item):
            if paragraph:
                blocks.append(paragraph)
            paragraph = _new_paragraph(item)
        else:
            _extend_paragraph(paragraph, item)

    if paragraph:
        blocks.append(paragraph)
    return blocks


def _glue_fragments(blocks: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    """把被公式打散的小块粘成一整块。

    独立成行的公式会抽出一堆孤立符号（"k"、"i=1"、"(2)" 之类）。它们紧挨着彼此，
    按「小块贴着谁」把相邻的小块依次粘起来，公式就成了一个块。
    粘的前提是纵向几乎贴着；正文段落之间、标题之间的间距都比这个大，不会被误粘。

    粘出来的块如果大半字符来自数学字体，就标成公式块，交给前端按原图显示。
    """
    glued: list[dict[str, Any]] = []
    for block in blocks:
        previous = glued[-1] if glued else None
        is_fragment = lambda item: (item["x1"] - item["x0"]) < SHORT_BLOCK_RATIO * page_width  # noqa: E731
        glueable = (
            previous is not None
            and previous["kind"] in {"text", "formula"}
            and block["kind"] == "text"
            and not _LIST_START.match(block["text"].strip())
            and is_fragment(previous)
            and is_fragment(block)
        )

        # 纵向重叠说明是同一个视觉单元被打散的两截；上下堆叠则必须几乎贴在一起。
        # 用区间重叠而不是端点差值：公式编号常常落在公式块的纵向范围之内，
        # 端点上比差值会比出个很大的负数，看着像离得很远，其实就在旁边。
        overlap = min(previous["y1"], block["y1"]) - max(previous["y0"], block["y0"]) if previous else 0.0
        # 上下堆叠时按两块里较小的字号算容差。用较大的会把小页眉和大标题粘到一起：
        # 大标题把容差撑大了，本来明显是两行的距离就被当成一行。
        size = min(previous["size"], block["size"]) if previous else 1.0
        adjacent = overlap > 0 or -overlap <= GLUE_STACK_RATIO * size

        if glueable and adjacent:
            previous["text"] = f"{previous['text']} {block['text']}".strip()
            segments = previous.setdefault("segments", [])
            if segments and segments[-1]["kind"] == "text":
                segments[-1]["text"] += " "
            else:
                segments.append({"kind": "text", "text": " "})
            segments.extend(dict(segment) for segment in block.get("segments", []))
            previous["x0"] = min(previous["x0"], block["x0"])
            previous["y0"] = min(previous["y0"], block["y0"])
            previous["x1"] = max(previous["x1"], block["x1"])
            previous["y1"] = max(previous["y1"], block["y1"])
            previous["size"] = max(previous["size"], block["size"])
            previous["chars"] += block["chars"]
            previous["math_chars"] += block["math_chars"]
            continue
        glued.append(block)

    for block in glued:
        if block["kind"] == "text" and block["chars"]:
            ratio = block["math_chars"] / block["chars"]
            words = len(_WORD.findall(block["text"]))
            if ratio >= MATH_RATIO and (ratio >= MATH_RATIO_STRONG or words <= MAX_FORMULA_WORDS):
                block["kind"] = "formula"
    return glued


# ------------------------------------------------------------------ 页眉页脚

def _repeated_marginal_text(page_items: list[list[dict[str, Any]]]) -> set[str]:
    """找出在多数页面顶部或底部重复出现的文本，这些是页眉页脚，不是正文。"""
    seen_on: dict[str, int] = defaultdict(int)
    for items in page_items:
        shapes = {
            _shape(item["text"])
            for item in items
            if item["text"] and (item["y1"] <= TOP_BAND or item["y0"] >= BOTTOM_BAND)
        }
        for shape in shapes:
            seen_on[shape] += 1

    threshold = max(3, len(page_items) * REPEAT_RATIO)
    return {shape for shape, count in seen_on.items() if count >= threshold}


def _is_marginal(item: dict[str, Any], repeated: set[str]) -> bool:
    if not item["text"]:
        return False
    in_band = item["y1"] <= TOP_BAND or item["y0"] >= BOTTOM_BAND
    return in_band and _shape(item["text"]) in repeated


# ---------------------------------------------------------------------- 主流程

def _block_id(doc_id: str, page: int, bbox: tuple[float, float, float, float], text: str) -> str:
    """稳定主键：文档编号 + 页码 + 归一化坐标 + 文本。

    必须带上文档编号。只用页码和坐标的话，两份不同文献里位置相同的段落会算出同一个
    主键，后上传的那份会把前一份的段落顶掉，批注和对话跟着串台。文档编号取自文件内容，
    所以同一份 PDF 重复上传仍然得到同一批主键，批注留得住。
    """
    key = "{d}|{p}|{a:.4f},{b:.4f},{c:.4f},{e:.4f}|{t}".format(
        d=doc_id,
        p=page,
        a=bbox[0],
        b=bbox[1],
        c=bbox[2],
        e=bbox[3],
        t=_normalize_text(text),
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _to_blocks(
    ordered: list[dict[str, Any]], page_index: int, width: float, height: float
) -> list[dict[str, Any]]:
    produced: list[dict[str, Any]] = []
    for block in ordered:
        bbox = (
            max(0.0, block["x0"] / width),
            max(0.0, block["y0"] / height),
            min(1.0, block["x1"] / width),
            min(1.0, block["y1"] / height),
        )
        # 只夹上下界还不够，异常块可能给出反着的框，宽高变成负数，
        # 前端的热区和锚点会全部错位。这种块直接丢掉。
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        text = _repair_hyphen_gaps(_normalize_text(block["text"]))
        if block["kind"] not in {"figure", "table"} and not _has_readable_content(text):
            continue
        segments: list[dict[str, Any]] = []
        for segment in block.get("segments", []):
            segment_kind = segment.get("kind")
            if segment_kind not in {"text", "math"}:
                continue
            segment_text = _repair_hyphen_gaps(
                _clean_segment_text(str(segment.get("text", "")))
            )
            if not segment_text.strip():
                continue
            sx0 = max(0.0, float(segment["x0"]) / width)
            sy0 = max(0.0, float(segment["y0"]) / height)
            sx1 = min(1.0, float(segment["x1"]) / width)
            sy1 = min(1.0, float(segment["y1"]) / height)
            if sx1 <= sx0 or sy1 <= sy0:
                continue
            segments.append(
                {
                    "kind": segment_kind,
                    "text": segment_text,
                    "x0": sx0,
                    "y0": sy0,
                    "x1": sx1,
                    "y1": sy1,
                }
            )
        produced.append(
            {
                "page": page_index,
                "kind": block["kind"],
                "x0": bbox[0],
                "y0": bbox[1],
                "x1": bbox[2],
                "y1": bbox[3],
                "text": text,
                "segments": segments,
            }
        )
    return produced


def extract_blocks(pdf_path: str, doc_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回 (blocks, meta)。meta 含页数、标题和每页尺寸，供前端核对坐标基准。"""
    page_items: list[list[dict[str, Any]]] = []
    pages: list[dict[str, Any]] = []

    with pymupdf.open(pdf_path) as doc, pdfplumber.open(pdf_path) as plumber:
        meta_title = ((doc.metadata or {}).get("title") or "").strip()
        for page_index, page in enumerate(doc):
            rect = page.rect
            width = rect.width or 1.0
            height = rect.height or 1.0
            pages.append({"page": page_index, "width": width, "height": height})

            lines = _visual_lines(page)
            figures, remaining = _drawing_regions(page, lines, width, height)
            tables, remaining = _table_regions(
                plumber.pages[page_index], remaining, width, height
            )
            items = remaining + _image_regions(page) + figures + tables
            ordered = _group_paragraphs(_xy_cut(items, (width, height)))
            glued = _glue_fragments(ordered, width)
            page_items.append(_to_blocks(glued, page_index, width, height))

    repeated = _repeated_marginal_text(page_items)
    blocks: list[dict[str, Any]] = []
    for items in page_items:
        for item in items:
            if _is_marginal(item, repeated):
                continue
            bbox = (item["x0"], item["y0"], item["x1"], item["y1"])
            blocks.append(
                {
                    "id": _block_id(doc_id, item["page"], bbox, item["text"]),
                    "page": item["page"],
                    "kind": item["kind"],
                    "order_index": len(blocks),
                    "x0": item["x0"],
                    "y0": item["y0"],
                    "x1": item["x1"],
                    "y1": item["y1"],
                    "text": item["text"],
                    "segments": item["segments"],
                }
            )

    meta = {"page_count": len(pages), "title": meta_title, "pages": pages}
    return blocks, meta
