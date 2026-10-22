"""接口冒烟测试：校验上传、解析、批注持久化、PDF 取回和错误提示。

需要服务已经在 127.0.0.1:8756 运行。
运行：.venv\\Scripts\\python.exe backend\\tests\\smoke_api.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8756")
SAMPLE = ROOT / "samples" / "sample-paper.pdf"

failures: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  通过  {label}")
    else:
        failures.append(label)
        print(f"  失败  {label} {extra}")


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(BASE + path, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return response.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return error.code, raw.decode("utf-8", "replace")


def upload(path: Path) -> tuple[int, object]:
    boundary = "----smoke" + uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(BASE + "/api/documents", data=b"".join(parts), method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def upload_skin(image_bytes: bytes, name: str) -> tuple[int, object]:
    """上传一张壁纸当皮肤。和上传 PDF 一样，手拼 multipart。"""
    boundary = "----skinsmoke" + uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            'Content-Disposition: form-data; name="file"; filename="cover.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode(),
        image_bytes,
        f"\r\n--{boundary}\r\n".encode(),
        'Content-Disposition: form-data; name="name"\r\n\r\n'.encode(),
        name.encode(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        BASE + "/api/skins", data=b"".join(parts), method="POST"
    )
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def make_test_wallpaper() -> bytes:
    """现画一张小图当上传素材：左边深、右边亮，主色应该被算成一个蓝色。"""
    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    for x in range(64):
        for y in range(64):
            pixels[x, y] = (20 + x * 2, 40 + y * 2, 90 + x)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def main() -> int:
    print("健康检查")
    status, health = call("GET", "/api/health")
    check("健康检查返回 200", status == 200, str(health))
    check("返回两项模型开关", isinstance(health, dict) and set(health) == {"chat", "translate"})

    print("\n上传与解析")
    # 这份样张是测试自己的素材，跑第二遍时库里已经有它了。先记住它进来时的状态：
    # 新库就断言「默认待读、未分类」，老库就断言「重复上传不覆盖用户改过的状态」。
    sample_id = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()[:16]
    _, existing_documents = call("GET", "/api/documents")
    before = None
    if isinstance(existing_documents, list):
        before = next((item for item in existing_documents if item["id"] == sample_id), None)

    status, result = upload(SAMPLE)
    check("上传返回 201", status == 201)
    assert isinstance(result, dict)
    document = result["document"]
    blocks = result["blocks"]
    doc_id = document["id"]
    check("识别出标题", bool(document["title"]))
    check("页数为 2", document["page_count"] == 2, str(document["page_count"]))
    check("解析出多个段落", len(blocks) >= 8, str(len(blocks)))
    if before is None:
        check("新上传文献默认进入待读", document["read_status"] == "unread", str(document))
        check("新上传文献默认未分类", document["category"] == "", str(document))
    else:
        check(
            "重复上传保留已有阅读状态",
            document["read_status"] == before["read_status"],
            str(document),
        )
        check("重复上传保留已有分类", document["category"] == before["category"], str(document))

    texts = [b["text"] for b in blocks]
    print("  阅读顺序：")
    for block in blocks:
        print(f"    p{block['page'] + 1} #{block['order_index']:02d} {block['text'][:52]}")

    first_page = [b for b in blocks if b["page"] == 0]
    joined = " | ".join(b["text"][:24] for b in first_page)
    check("标题排在最前", first_page[0]["text"].startswith("Attention-Guided"), joined)
    check("通栏摘要排在正文之前", first_page[1]["text"].startswith("Reading a long research paper"), joined)

    # 栏内段落比通栏的标题、摘要窄，用宽度先把两者分开。
    in_column = [(i, b) for i, b in enumerate(first_page) if (b["x1"] - b["x0"]) < 0.45]
    left_column = [i for i, b in in_column if b["x0"] < 0.4]
    right_column = [i for i, b in in_column if b["x0"] >= 0.4]
    check("左栏与右栏都被分出来", len(left_column) >= 5 and len(right_column) >= 5, joined)
    check(
        "左栏整栏读完后才读右栏",
        max(left_column) < min(right_column),
        f"左栏位置 {left_column}，右栏位置 {right_column}",
    )
    check(
        "左栏第一条是 Introduction",
        first_page[min(left_column)]["text"].startswith("1 Introduction")
        and first_page[max(left_column)]["text"].startswith("Retrieval has two modes"),
        joined,
    )

    print("\n批注持久化")
    target = blocks[0]
    status, patched = call(
        "PATCH",
        f"/api/blocks/{target['id']}",
        {"translation": "测试译文", "note": "测试笔记"},
    )
    check("补丁返回 200", status == 200, str(patched))
    assert isinstance(patched, dict)
    check("译文已写入", patched["translation"] == "测试译文")
    check("笔记已写入", patched["note"] == "测试笔记")
    check("笔记计入留痕标记", patched["has_note"] == 1)
    check(
        "段落带类型字段",
        patched.get("kind") in {"text", "formula", "figure", "table"},
        str(patched.get("kind")),
    )
    check("段落带行内片段字段", isinstance(patched.get("segments"), list), str(patched.get("segments"))[:80])
    check("已废弃的 status 字段不再出现", "status" not in patched)

    status, question_list = call("GET", f"/api/documents/{doc_id}/questions")
    check("疑问清单返回 200", status == 200, str(question_list))
    check(
        "写过笔记的段落出现在疑问清单里",
        isinstance(question_list, list) and any(item["id"] == target["id"] for item in question_list),
        str(question_list),
    )

    status, again = upload(SAMPLE)
    check("重复上传仍是 201", status == 201)
    assert isinstance(again, dict)
    reflowed = next(b for b in again["blocks"] if b["id"] == target["id"])
    check("重新解析后批注仍在", reflowed["translation"] == "测试译文" and reflowed["note"] == "测试笔记")
    check("段落总数不变", len(again["blocks"]) == len(blocks))

    print("\n状态与分类")
    status, updated_document = call(
        "PATCH",
        f"/api/documents/{doc_id}",
        {"read_status": "read", "category": "测试分类"},
    )
    check("文献可以标记已读", status == 200 and updated_document["read_status"] == "read")
    check("文献可以设置分类", updated_document["category"] == "测试分类")
    status, created_category = call("POST", "/api/categories", {"name": "测试分类"})
    check("新增分类返回 201", status == 201, str(created_category))
    status, category_list = call("GET", "/api/categories")
    check(
        "分类列表包含新分类",
        status == 200 and "测试分类" in category_list["categories"],
        str(category_list),
    )

    print("\n文件与列表")
    with urllib.request.urlopen(f"{BASE}/api/documents/{doc_id}/file") as response:
        head = response.read(5)
    check("PDF 端点返回 PDF", head.startswith(b"%PDF"), str(head))

    status, listing = call("GET", "/api/documents")
    check("文献列表包含本文", any(item["id"] == doc_id for item in listing))  # type: ignore[union-attr]

    # 把样张放回进来时的样子，别让测试留下的「已读 / 测试分类」堆在用户的文献库里。
    if before is not None:
        call(
            "PATCH",
            f"/api/documents/{doc_id}",
            {"read_status": before["read_status"], "category": before["category"]},
        )

    print("\n皮肤")
    status, skin_list = call("GET", "/api/skins")
    check("皮肤列表返回 200", status == 200, str(skin_list))
    assert isinstance(skin_list, dict)
    listed = skin_list["skins"]
    check("原味排在第一个", listed[0]["id"] == "plain", str(listed[:1]))
    check(
        "内置皮肤都带壁纸和算出来的明暗",
        all(
            item["cover"] and item["mode"] in {"light", "dark"}
            for item in listed
            if item["id"] != "plain"
        ),
        str([(item["id"], item["mode"]) for item in listed]),
    )

    status, previous = call("GET", "/api/appearance")
    check("外观接口返回当前设置", status == 200 and "appearance" in previous, str(previous))
    stored = previous["appearance"]  # type: ignore[index]

    status, refused = call("PUT", "/api/appearance", {"skin": "不存在的皮肤"})
    check("选一套不存在的皮肤会被拒绝", status == 400, f"{status} {refused}")

    status, saved = call(
        "PUT",
        "/api/appearance",
        {
            "skin": "ink-night",
            "mode": "dark",
            "accent": "#66b3c9",
            "blur": 20,
            "panel_opacity": 0.5,
            "mask": 0.25,
            "wallpaper_blur": 0,
            "reader_shade": 0.4,
        },
    )
    check(
        "外观设置能保存",
        status == 200 and saved["appearance"]["skin"] == "ink-night",  # type: ignore[index]
        str(saved),
    )
    status, read_back = call("GET", "/api/appearance")
    check(
        "外观设置读得回来",
        read_back["appearance"]["blur"] == 20 and read_back["appearance"]["mode"] == "dark",  # type: ignore[index]
        str(read_back),
    )

    # 上传一张图当皮肤，再删掉：这条路要走得通，还不能在库里留垃圾。
    status, created = upload_skin(make_test_wallpaper(), "冒烟测试皮肤")
    check("上传图片能生成皮肤", status == 201, str(created))
    assert isinstance(created, dict)
    new_skin = created["skin"]
    check(
        "新皮肤算出了明暗和主色",
        new_skin["mode"] in {"light", "dark"} and new_skin["accent"].startswith("#"),
        str(new_skin),
    )
    status, _ = call("DELETE", f"/api/skins/{new_skin['id']}")
    check("自己传的皮肤能删除", status == 204, str(status))
    status, after_delete = call("GET", "/api/skins")
    check(
        "删掉之后列表里不再出现",
        all(item["id"] != new_skin["id"] for item in after_delete["skins"]),  # type: ignore[index]
        str([item["id"] for item in after_delete["skins"]]),  # type: ignore[index]
    )

    # 皮肤也放回进来时的样子。
    call("PUT", "/api/appearance", stored)

    print("\n模型未配置时的提示")
    if health.get("chat"):
        print("  跳过  当前服务已配置对话模型")
    else:
        status, payload = call(
            "POST",
            f"/api/documents/{doc_id}/messages",
            {"content": "这篇讲了什么", "scope": "full"},
        )
        if status == 409:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            check("缺少模型配置返回 409 并说明原因", "未配置" in str(detail), str(detail))
        else:
            check("缺少模型配置返回 409", False, f"实际 {status} {payload}")

    print()
    if failures:
        print(f"失败 {len(failures)} 项：" + "；".join(failures))
        return 1
    print("接口冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

