"""生成一份样例论文 PDF，用来调试和演示。

运行：.venv\\Scripts\\python.exe backend\\tests\\make_sample.py
输出：samples/sample-paper.pdf
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "samples" / "sample-paper.pdf"

PAGE_W, PAGE_H = 612, 792
LEFT = (60, 230, 297, 730)
RIGHT = (315, 230, 552, 730)

TITLE = "Attention-Guided Retrieval for Long-Context Scientific Reading"

AUTHORS = "Wen Zhang, Lina Qiu, and Hao Chen"

ABSTRACT = (
    "Reading a long research paper is not a linear activity: a reader jumps between a "
    "definition, the method that depends on it, and the experiment that tests it. We study "
    "whether retrieval can follow that behaviour. We introduce a paragraph-level index that "
    "stores where each passage sits on the page, and we show that grounding the answer in the "
    "retrieved passage reduces unsupported statements by 41 percent on a held-out set of 320 "
    "papers. The index costs one embedding per paragraph and requires no fine-tuning."
)

COLUMN_ONE = [
    (
        "1  Introduction",
        "Scientific documents are dense, and their structure carries meaning that a flat text "
        "extraction discards. A definition in Section 2 constrains a method in Section 3, while "
        "the evidence for the method appears in a table on a later page. Readers navigate this "
        "graph of dependencies constantly, but the tools they use present the paper as a scroll "
        "of undifferentiated text.",
    ),
    (
        "",
        "Reading behaviour is also local. A reader stops at a paragraph, asks what it means, and "
        "only occasionally widens the question to the whole document. This matters for retrieval, "
        "because the evidence needed to answer a local question is usually local as well. Sending "
        "the whole paper to a model wastes context and introduces distractors that the model "
        "cannot distinguish from the relevant passage.",
    ),
    (
        "2  Method",
        "We split the document into paragraphs using a recursive layout cut. Each paragraph becomes "
        "an independent unit with a stable identifier derived from its page number, its normalised "
        "bounding box, and its text. Because the identifier is derived from content and geometry "
        "rather than from position in a stream, annotations survive re-parsing.",
    ),
    (
        "",
        "Retrieval has two modes. In local mode we take the anchored paragraph and its immediate "
        "neighbours, which keeps the context small and the answer grounded. In global mode we embed "
        "every paragraph and retrieve the most similar ones by cosine similarity.",
    ),
]

COLUMN_TWO = [
    (
        "3  Experiments",
        "We evaluate on 320 papers from three domains. For each paper we collect 12 questions "
        "written by graduate students while reading. Two annotators label every generated sentence "
        "as supported or unsupported by the cited passage.",
    ),
    (
        "",
        "Table 1 reports the main result. Grounding the answer in retrieved paragraphs raises the "
        "supported-sentence rate from 0.62 to 0.88, while the average context length falls from "
        "14,200 tokens to 1,900 tokens. The gain holds across all three domains.",
    ),
    (
        "4  Discussion",
        "The local and global modes fail in different ways. Local mode cannot answer questions that "
        "span sections, and global mode occasionally retrieves a passage that is topically similar "
        "but logically unrelated. A reader who switches between the two modes manually recovers "
        "most of the lost accuracy.",
    ),
    (
        "5  Conclusion",
        "Paragraph-level grounding is a cheap and effective way to make a reading assistant "
        "faithful. The reconstruction of reading order remains the main source of error: when the "
        "layout cut misjudges a column boundary, the neighbouring paragraphs are no longer the "
        "right ones, and the local answer degrades.",
    ),
]

PAGE_TWO = [
    (
        "A  Appendix: Implementation Notes",
        "The layout cut processes each page independently. It measures the widest uncovered gap in "
        "the horizontal and vertical projections, compares the two in points, and splits at the "
        "larger one. The recursion stops when neither projection contains a gap wide enough to be "
        "structural.",
    ),
    (
        "",
        "Paragraph identifiers are 20 hexadecimal characters taken from a SHA-1 digest. Two parses "
        "of the same file with the same parser produce identical identifiers, so user annotations "
        "are preserved across re-uploads.",
    ),
    (
        "B  Limitations",
        "Scan-only papers require OCR before the layout cut can run. Very wide tables that alternate "
        "between one and two columns within a single region may be split incorrectly.",
    ),
]


def write_column(page: pymupdf.Page, rect: tuple[int, int, int, int], parts: list[tuple[str, str]]) -> None:
    _, top, _, _ = rect
    x0, _, x1, bottom = rect
    cursor = top
    for heading, body in parts:
        if heading:
            page.insert_textbox(pymupdf.Rect(x0, cursor, x1, cursor + 20), heading, fontsize=11)
            cursor += 20
        used = page.insert_textbox(
            pymupdf.Rect(x0, cursor, x1, bottom), body, fontsize=9, lineheight=1.35
        )
        cursor = bottom - used + 14


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_textbox(pymupdf.Rect(60, 56, 552, 92), TITLE, fontsize=16)
    page.insert_textbox(pymupdf.Rect(60, 96, 552, 112), AUTHORS, fontsize=10)
    page.insert_textbox(pymupdf.Rect(60, 126, 552, 214), ABSTRACT, fontsize=9, lineheight=1.35)
    write_column(page, LEFT, COLUMN_ONE)
    write_column(page, RIGHT, COLUMN_TWO)

    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    write_column(page, (60, 90, 297, 730), PAGE_TWO)
    write_column(page, (315, 90, 552, 730), COLUMN_TWO[:2])

    doc.set_metadata({"title": "Attention-Guided Retrieval for Long-Context Scientific Reading"})
    doc.save(OUTPUT)
    doc.close()
    print(f"已生成 {OUTPUT}")


if __name__ == "__main__":
    main()

