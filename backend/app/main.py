"""HTTP 接口层。"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db, llm, parser, rag, skins
from .config import ROOT, save_settings, settings

# Python 的 mimetypes 不认识 .mjs，默认发成 text/plain，浏览器会拒绝按模块加载
# PDF.js 的 worker。这里显式登记，否则前端报 "Failed to fetch dynamically imported module"。
mimetypes.add_type("text/javascript", ".mjs")

# 文献编号是文件内容的 sha256 前 16 位，只可能是小写十六进制。
# 校验它既是数据约束，也挡掉了把 doc_id 拼成 ../.. 去读目录外文件的路子。
DOC_ID = re.compile(r"^[0-9a-f]{16}$")

# 上传体积上限。解析要把整份 PDF 交给 PyMuPDF，超大文件会把内存吃满。
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
UPLOAD_CHUNK = 1 << 20

app = FastAPI(title="PaperLens")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_static(request: Request, call_next):
    """静态产物一律禁止缓存。

    这是本地单人工具，缓存省不下多少时间，但一旦浏览器把某次失败响应（比如内容类型
    不对的 worker）缓存下来，后面怎么重启服务都没用。直接不缓存，省掉这类排查。
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.exception_handler(llm.ConfigError)
def _config_error(_request: Request, exc: llm.ConfigError) -> JSONResponse:
    """模型没配好就直接把原因告诉前端，不做任何兜底。"""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def _value_error(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _require_doc_id(doc_id: str) -> str:
    """校验文献编号格式，顺带挡掉拼接路径读取目录外文件的做法。"""
    if not DOC_ID.fullmatch(doc_id):
        raise HTTPException(status_code=404, detail="文献不存在")
    return doc_id


# ------------------------------------------------------------------ schemas

class BlockPatch(BaseModel):
    translation: str | None = None
    note: str | None = None


class AskRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    scope: str = Field(default="full", pattern="^(full|block)$")

    @field_validator("content")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("问题不能为空")
        return text


class NoteRequest(BaseModel):
    content: str


class ModelRoute(BaseModel):
    base_url: str = ""
    api_key: str | None = None
    model: str = ""


class ConfigRequest(BaseModel):
    chat: ModelRoute
    translate: ModelRoute = Field(default_factory=ModelRoute)
    note_template: str | None = Field(default=None, max_length=20000)
    agent_prompt: str | None = Field(default=None, max_length=20000)


class DocumentPatch(BaseModel):
    read_status: str | None = Field(default=None, pattern="^(unread|read)$")
    category: str | None = Field(default=None, max_length=40)

    @field_validator("category")
    @classmethod
    def _strip_category(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("分类名不能为空")
        return text


class ModelListRequest(BaseModel):
    kind: str = Field(pattern="^(chat|translate)$")
    base_url: str
    api_key: str | None = None


class AppearanceInput(BaseModel):
    """当前用哪套皮肤，以及这套皮肤的参数。全部落 app_settings。"""

    skin: str = Field(default="plain", max_length=40)
    mode: str = Field(default="system", pattern="^(system|light|dark)$")
    accent: str = Field(default="", max_length=16)
    blur: float = Field(default=0, ge=0, le=40)
    panel_opacity: float = Field(default=1, ge=0.2, le=1)
    mask: float = Field(default=0, ge=0, le=0.9)
    wallpaper_blur: float = Field(default=0, ge=0, le=30)
    reader_shade: float = Field(default=0, ge=0, le=0.9)


# --------------------------------------------------------------------- misc

@app.get("/api/health")
def health() -> dict[str, Any]:
    """报告各模型是否配置齐全，前端据此提示用户填 .env。"""
    try:
        translate = all(settings.translation_route())
    except ValueError:
        # 翻译配置只填了一半，属于配错，这里按「没配好」上报。
        translate = False
    return {
        "chat": bool(settings.chat_base_url and settings.chat_api_key and settings.chat_model),
        "translate": translate,
    }


def _config_view() -> dict[str, Any]:
    return {
        "chat": {
            "base_url": settings.chat_base_url,
            "model": settings.chat_model,
            "api_key_set": bool(settings.chat_api_key),
        },
        "translate": {
            "base_url": settings.translate_base_url,
            "model": settings.translate_model,
            "api_key_set": bool(settings.translate_api_key),
        },
        "note_template": db.get_setting("note_template", ""),
        "agent_prompt": _read_agent_prompt(),
    }


def _read_agent_prompt() -> str:
    path = settings.data_path / "agent.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_agent_prompt(content: str) -> None:
    path = settings.data_path / "agent.md"
    path.write_text(content.strip(), encoding="utf-8")


def _resolve_route(route: ModelRoute, current: tuple[str, str, str]) -> tuple[str, str, str]:
    """api_key 为 null 时保持原值，显式空字符串表示清除。"""
    base_url = route.base_url.strip()
    model = route.model.strip()
    api_key = current[1] if route.api_key is None else route.api_key.strip()
    return base_url, api_key, model


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {"config": _config_view(), "health": health()}


@app.put("/api/config")
def put_config(body: ConfigRequest) -> dict[str, Any]:
    chat = _resolve_route(
        body.chat, (settings.chat_base_url, settings.chat_api_key, settings.chat_model)
    )
    translate = _resolve_route(
        body.translate,
        (settings.translate_base_url, settings.translate_api_key, settings.translate_model),
    )

    for label, route in (("对话模型", chat), ("翻译模型", translate)):
        if not all(route):
            raise ValueError(f"{label}的 base_url / api_key / model 三项都必填")

    if not settings.skip_connection_test:
        try:
            llm.test_chat_route(*chat)
            llm.test_chat_route(*translate)
        except Exception as exc:
            raise ValueError(f"模型连接测试失败：{exc}") from exc

    save_settings(
        {
            "CHAT_BASE_URL": chat[0],
            "CHAT_API_KEY": chat[1],
            "CHAT_MODEL": chat[2],
            "TRANSLATE_BASE_URL": translate[0],
            "TRANSLATE_API_KEY": translate[1],
            "TRANSLATE_MODEL": translate[2],
        }
    )
    if body.note_template is not None:
        db.set_setting("note_template", body.note_template.strip())
    if body.agent_prompt is not None:
        _write_agent_prompt(body.agent_prompt)
    return {"config": _config_view(), "health": health()}


@app.post("/api/config/models")
def get_model_list(body: ModelListRequest) -> dict[str, list[str]]:
    base_url = body.base_url.strip()
    if not base_url:
        raise ValueError("先填写 Base URL，再拉取模型列表")
    current_key = {
        "chat": settings.chat_api_key,
        "translate": settings.translate_api_key,
    }[body.kind]
    api_key = body.api_key if body.api_key is not None else current_key
    if not api_key:
        raise ValueError("先填写 API Key，再拉取模型列表")
    try:
        return {"models": llm.list_models(base_url, api_key)}
    except Exception as exc:
        raise ValueError(f"拉取模型列表失败：{exc}") from exc


# ------------------------------------------------------------------- 皮肤

@app.get("/api/skins")
def get_skins() -> dict[str, Any]:
    """列出原味、内置皮肤和用户自己传的皮肤。"""
    return {"skins": skins.list_skins()}


@app.get("/api/skins/{skin_id}/cover")
def get_skin_cover(skin_id: str) -> FileResponse:
    path = skins.cover_path(skin_id)
    if not path:
        raise HTTPException(status_code=404, detail="皮肤图片不存在")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@app.post("/api/skins", status_code=201)
async def upload_skin(
    file: UploadFile = File(...),
    name: str = Form(default=""),
) -> dict[str, Any]:
    """上传一张壁纸，立刻变成一套可用皮肤。"""
    payload = await file.read()
    if not payload:
        raise ValueError("文件是空的")
    if len(payload) > skins.MAX_COVER_BYTES:
        limit = skins.MAX_COVER_BYTES // 1024 // 1024
        raise ValueError(f"图片超过 {limit} MB，请先压小再上传")
    try:
        created = skins.create_skin(name, file.filename or "", payload)
    except Exception as exc:
        raise ValueError(f"这张图用不了：{exc}") from exc
    return {"skin": created}


@app.delete("/api/skins/{skin_id}", status_code=204)
def delete_skin(skin_id: str) -> None:
    skins.delete_skin(skin_id)


def _appearance_default() -> dict[str, Any]:
    return {
        "skin": "plain",
        "mode": "system",
        "accent": "",
        "blur": 0.0,
        "panel_opacity": 1.0,
        "mask": 0.0,
        "wallpaper_blur": 0.0,
        "reader_shade": 0.0,
    }


@app.get("/api/appearance")
def get_appearance() -> dict[str, Any]:
    raw = db.get_setting("appearance", "")
    if not raw:
        return {"appearance": _appearance_default()}
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("外观设置读不出来，在界面上重新选一次皮肤即可") from exc
    return {"appearance": {**_appearance_default(), **stored}}


@app.put("/api/appearance")
def put_appearance(body: AppearanceInput) -> dict[str, Any]:
    if skins.get_skin(body.skin) is None:
        raise ValueError("这套皮肤不存在，请重新选一次")
    payload = body.model_dump()
    db.set_setting("appearance", json.dumps(payload, ensure_ascii=False))
    return {"appearance": payload}


# ---------------------------------------------------------------- documents

@app.post("/api/documents", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise ValueError("只支持 PDF 文件")

    # 分块读、边读边判上限，避免一个超大文件直接把内存吃满。
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB，请先拆分再上传")
        chunks.append(chunk)
    payload = b"".join(chunks)

    if not payload:
        raise ValueError("文件是空的")
    if not payload.startswith(b"%PDF-"):
        raise ValueError("这个文件不是 PDF（缺少 %PDF- 文件头）")

    doc_id = hashlib.sha256(payload).hexdigest()[:16]
    pdf_path = settings.data_path / f"{doc_id}.pdf"
    pdf_path.write_bytes(payload)

    try:
        blocks, meta = parser.extract_blocks(str(pdf_path), doc_id)
        if not blocks:
            raise ValueError("这个 PDF 没有提取到任何文字，可能是扫描件，需要先做 OCR")
        db.save_document(
            doc_id,
            file.filename or f"{doc_id}.pdf",
            meta["title"],
            meta["page_count"],
            [{"doc_id": doc_id, **block} for block in blocks],
        )
    except Exception:
        # 解析失败或入库失败都不能留下半成品文件。
        pdf_path.unlink(missing_ok=True)
        raise

    document = db.get_document(doc_id)
    return {"document": document, "blocks": db.get_blocks(doc_id), "pages": meta["pages"]}


@app.get("/api/documents")
def list_documents() -> list[dict[str, Any]]:
    return db.list_documents()


@app.get("/api/categories")
def get_categories() -> dict[str, list[str]]:
    return {"categories": db.list_categories()}


@app.post("/api/categories", status_code=201)
def create_category(body: CategoryRequest) -> dict[str, list[str]]:
    return {"categories": db.add_category(body.name)}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> dict[str, Any]:
    document = db.get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文献不存在")
    return {"document": document, "note": db.get_doc_note(doc_id)}


@app.patch("/api/documents/{doc_id}")
def patch_document(doc_id: str, patch: DocumentPatch) -> dict[str, Any]:
    _require_doc_id(doc_id)
    updated = db.update_document(
        doc_id,
        read_status=patch.read_status,
        category=patch.category,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="文献不存在")
    return updated


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> None:
    _require_doc_id(doc_id)
    db.delete_document(doc_id)
    (settings.data_path / f"{doc_id}.pdf").unlink(missing_ok=True)


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: str) -> FileResponse:
    _require_doc_id(doc_id)
    pdf_path = settings.data_path / f"{doc_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(pdf_path, media_type="application/pdf")


@app.get("/api/documents/{doc_id}/blocks")
def get_blocks(doc_id: str) -> list[dict[str, Any]]:
    return db.get_blocks(doc_id)


@app.get("/api/documents/{doc_id}/questions")
def get_questions(doc_id: str) -> list[dict[str, Any]]:
    """这篇文献里问过或记过笔记的段落，用来回顾哪里没看懂。"""
    return db.list_questions(doc_id)


@app.get("/api/documents/{doc_id}/overview")
def get_document_overview(doc_id: str, refresh: bool = False) -> dict[str, Any]:
    document = db.get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文献不存在")
    overview = None if refresh else db.get_document_overview(doc_id)
    if overview is None:
        context = rag.document_context(doc_id)
        if not context.strip():
            raise ValueError("这篇文献没有可用于生成梗概的段落")
        overview = llm.document_overview(context)
        db.save_document_overview(doc_id, overview)
    return {
        "document": document,
        "overview": overview,
        "questions": db.reading_record(doc_id),
    }


# ------------------------------------------------------------------- blocks

@app.patch("/api/blocks/{block_id}")
def patch_block(block_id: str, patch: BlockPatch) -> dict[str, Any]:
    block = db.update_block(block_id, **patch.model_dump(exclude_unset=True))
    if not block:
        raise HTTPException(status_code=404, detail="段落不存在")
    return block


@app.post("/api/blocks/{block_id}/translate")
def translate_block(block_id: str) -> dict[str, Any]:
    block = db.get_block(block_id)
    if not block:
        raise HTTPException(status_code=404, detail="段落不存在")
    translation = llm.translate(block["text"])
    updated = db.update_block(block_id, translation=translation)
    assert updated is not None
    return updated


@app.get("/api/blocks/{block_id}/messages")
def get_block_messages(block_id: str) -> list[dict[str, Any]]:
    block = db.get_block(block_id)
    if not block:
        raise HTTPException(status_code=404, detail="段落不存在")
    return db.get_messages(block["doc_id"], block_id)


@app.post("/api/blocks/{block_id}/messages", status_code=201)
def ask_about_block(block_id: str, body: AskRequest) -> dict[str, Any]:
    block = db.get_block(block_id)
    if not block:
        raise HTTPException(status_code=404, detail="段落不存在")
    doc_id = block["doc_id"]

    question = body.content
    # 先拿答案再落库：模型没配好或调用失败时，不会在历史里留下一句没有回答的提问。
    # 顺序也保证模型看到的历史里不含当前这个问题，否则同一个问题会被送进去两次。
    result = rag.ask(doc_id, question, block_id=block_id, scope=body.scope)
    db.add_message(doc_id, block_id, body.scope, "user", question)
    answer = db.add_message(
        doc_id, block_id, body.scope, "assistant", result["answer"], result["citations"]
    )
    return {"message": answer, "citations": result["citations"], "block": db.get_block(block_id)}


@app.delete("/api/blocks/{block_id}/messages", status_code=204)
def clear_block_messages(block_id: str) -> None:
    block = db.get_block(block_id)
    if not block:
        raise HTTPException(status_code=404, detail="段落不存在")
    db.clear_messages(block["doc_id"], block_id)


@app.post("/api/blocks/{block_id}/note")
def generate_block_note(block_id: str) -> dict[str, Any]:
    """按这段的原文和问答历史生成笔记，生成结果写入 note 字段。"""
    content = rag.reading_note(block_id)
    updated = db.update_block(block_id, note=content)
    assert updated is not None
    return updated


# ------------------------------------------------------- document level chat

@app.get("/api/documents/{doc_id}/messages")
def get_document_messages(doc_id: str) -> list[dict[str, Any]]:
    return db.get_messages(doc_id, None)


@app.post("/api/documents/{doc_id}/messages", status_code=201)
def ask_about_document(doc_id: str, body: AskRequest) -> dict[str, Any]:
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="文献不存在")
    question = body.content
    result = rag.ask(doc_id, question, block_id=None, scope="full")
    db.add_message(doc_id, None, body.scope, "user", question)
    answer = db.add_message(
        doc_id, None, body.scope, "assistant", result["answer"], result["citations"]
    )
    return {"message": answer, "citations": result["citations"]}


@app.put("/api/documents/{doc_id}/note")
def put_document_note(doc_id: str, body: NoteRequest) -> dict[str, str]:
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="文献不存在")
    db.set_doc_note(doc_id, body.content)
    return {"content": body.content}


@app.get("/api/documents/{doc_id}/markdown")
def export_markdown(doc_id: str) -> Response:
    """把这篇文献的阅读记录导出成 Markdown，方便拿去做综述素材。"""
    document = db.get_document(doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文献不存在")

    lines = [f"# {document['title'] or document['filename']}", ""]
    lines += [f"- 文件：{document['filename']}", f"- 页数：{document['page_count']}", ""]

    note = db.get_doc_note(doc_id).strip()
    lines += ["## 文献笔记", "", note or "（还没写）", ""]

    record = db.reading_record(doc_id)
    lines += ["## 留下疑问的段落", ""]
    if not record:
        lines += ["（还没标记）", ""]

    for entry in record:
        block = entry["block"]
        asked = f"问过 {block['message_count']} 次" if block["message_count"] else "只写了笔记"
        lines += [f"### 第 {block['page'] + 1} 页 · {asked}", "", f"> {block['text']}", ""]
        for message in entry["messages"]:
            who = "我" if message["role"] == "user" else "助手"
            lines += [f"**{who}**：{message['content']}", ""]
        if block["note"]:
            lines += ["**笔记**", "", block["note"], ""]
        lines += ["---", ""]

    body = "\n".join(lines)
    stem = (document["title"] or document["filename"] or doc_id).strip()
    safe = "".join(char for char in stem if char not in '\\/:*?"<>|')[:60] or doc_id
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


# 前端打包产物存在时顺带托管，这样生产环境只需要一个端口。
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")

