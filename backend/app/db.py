"""SQLite 存储层。

block 的主键是「页码 + 归一化坐标 + 文本」的哈希，同一份 PDF 用同一个解析器
反复解析会得到相同的主键，所以批注、翻译、对话都能挂在这个键上长期保存。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    title       TEXT,
    page_count  INTEGER NOT NULL,
    block_count INTEGER NOT NULL DEFAULT 0,
    overview    TEXT,
    read_status TEXT NOT NULL DEFAULT 'unread',
    category    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
    id          TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    page        INTEGER NOT NULL,
    order_index INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'text',
    x0 REAL NOT NULL,
    y0 REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    text        TEXT NOT NULL,
    segments    TEXT NOT NULL DEFAULT '[]',
    translation TEXT,
    note        TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_blocks_doc ON blocks(doc_id, order_index);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT NOT NULL,
    block_id   TEXT,
    scope      TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    citations  TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_scope ON messages(doc_id, block_id);

CREATE TABLE IF NOT EXISTS embeddings (
    block_id TEXT PRIMARY KEY,
    doc_id   TEXT NOT NULL,
    model    TEXT NOT NULL,
    vector   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doc_notes (
    doc_id     TEXT PRIMARY KEY,
    content    TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

_DB_FILE = settings.data_path / "library.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """把旧库补齐到当前表结构。

    早期版本用 status 记录「读过 / 读完」，那套设计已经废弃，改成了「这一块有没有
    对话或笔记」。这里重建 blocks 表：补上 kind，去掉 status，翻译和笔记原样搬过去。
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocks)")}
    if not ("kind" in columns and "status" not in columns):
        conn.executescript(
            """
            ALTER TABLE blocks RENAME TO blocks_legacy;
            CREATE TABLE blocks (
                id          TEXT PRIMARY KEY,
                doc_id      TEXT NOT NULL,
                page        INTEGER NOT NULL,
                order_index INTEGER NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'text',
                x0 REAL NOT NULL,
                y0 REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                text        TEXT NOT NULL,
                segments    TEXT NOT NULL DEFAULT '[]',
                translation TEXT,
                note        TEXT,
                updated_at  TEXT
            );
            INSERT INTO blocks
                (id, doc_id, page, order_index, kind, x0, y0, x1, y1, text, translation, note, updated_at)
            SELECT id, doc_id, page, order_index, 'text', x0, y0, x1, y1, text, translation, note, updated_at
            FROM blocks_legacy;
            DROP TABLE blocks_legacy;
            CREATE INDEX IF NOT EXISTS idx_blocks_doc ON blocks(doc_id, order_index);
            """
        )

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocks)")}
    if "segments" not in columns:
        # 旧库没有行内片段字段；新解析结果会补上，老段落仍按纯文字显示。
        conn.execute("ALTER TABLE blocks ADD COLUMN segments TEXT NOT NULL DEFAULT '[]'")

    document_columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    if "overview" not in document_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN overview TEXT")
    if "read_status" not in document_columns:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN read_status TEXT NOT NULL DEFAULT 'unread'"
        )
    if "category" not in document_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN category TEXT NOT NULL DEFAULT ''")

    # 插图一开始叫 image，现在统一叫 figure：矢量图、嵌入图片、画出来的表格都是同一类，
    # 界面上也只需要一种处理方式——显示原图。
    conn.execute("UPDATE blocks SET kind = 'figure' WHERE kind = 'image'")


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cur.fetchall()]


def _to_block(row: dict[str, Any]) -> dict[str, Any]:
    """把数据库里的行内片段 JSON 还原成前端直接可用的数组。"""
    raw = row.get("segments")
    if isinstance(raw, str):
        try:
            row["segments"] = json.loads(raw)
        except json.JSONDecodeError:
            row["segments"] = []
    elif raw is None:
        row["segments"] = []
    return row


# ---------------------------------------------------------------- documents

def _upsert_document(
    conn: sqlite3.Connection, doc_id: str, filename: str, title: str, page_count: int
) -> None:
    conn.execute(
        """
        INSERT INTO documents (id, filename, title, page_count, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            filename = excluded.filename,
            title = excluded.title,
            page_count = excluded.page_count
        """,
        (doc_id, filename, title, page_count, now()),
    )


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def list_categories() -> list[str]:
    raw = get_setting("doc_categories", "[]")
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return sorted({str(item).strip() for item in items if str(item).strip()}, key=str.lower)


def add_category(name: str) -> list[str]:
    categories = list_categories()
    clean = name.strip()
    if clean and clean not in categories:
        categories.append(clean)
    set_setting("doc_categories", json.dumps(categories, ensure_ascii=False))
    return list_categories()


def get_document_overview(doc_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT overview FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if not row or not row["overview"]:
            return None
        try:
            return json.loads(row["overview"])
        except json.JSONDecodeError:
            return None


def save_document_overview(doc_id: str, overview: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE documents SET overview = ? WHERE id = ?",
            (json.dumps(overview, ensure_ascii=False), doc_id),
        )


def save_document(
    doc_id: str,
    filename: str,
    title: str,
    page_count: int,
    blocks: list[dict[str, Any]],
) -> None:
    """文献记录和它的段落写在同一个事务里。

    分成两次写的话，段落那步失败就会留下一份没有段落的空文献，用户点了直接报错。
    """
    with connect() as conn:
        _upsert_document(conn, doc_id, filename, title, page_count)
        _write_blocks(conn, doc_id, blocks)


def list_documents() -> list[dict[str, Any]]:
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM documents ORDER BY created_at DESC"))


def get_document(doc_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None


def update_document(
    doc_id: str,
    *,
    read_status: str | None = None,
    category: str | None = None,
) -> dict[str, Any] | None:
    updates: dict[str, Any] = {}
    if read_status is not None:
        if read_status not in {"unread", "read"}:
            raise ValueError("文献状态只能是 unread 或 read")
        updates["read_status"] = read_status
    if category is not None:
        updates["category"] = category.strip()[:40]
    if updates:
        clause = ", ".join(f"{key} = :{key}" for key in updates)
        with connect() as conn:
            conn.execute(
                f"UPDATE documents SET {clause} WHERE id = :doc_id",
                {**updates, "doc_id": doc_id},
            )
    return get_document(doc_id)


def delete_document(doc_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM messages WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM embeddings WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM blocks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM doc_notes WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# ------------------------------------------------------------------- blocks

# 段落附带的两个派生字段：提过几次问、有没有写过笔记。
# 只数 user 消息：一问一答是两条记录，按条数算会把「问过 1 次」显示成 2 次。
# 前端用它们决定页边上要不要留标记——没碰过的段落不该留痕，页面才干净。
_BLOCK_SELECT = """
SELECT b.*,
       (SELECT COUNT(*) FROM messages m WHERE m.block_id = b.id AND m.role = 'user')
           AS message_count,
       CASE WHEN b.note IS NOT NULL AND TRIM(b.note) <> '' THEN 1 ELSE 0 END AS has_note
FROM blocks b
"""

def save_blocks(doc_id: str, blocks: list[dict[str, Any]]) -> None:
    """写入解析结果。

    主键相同即视为同一段落，只刷新位置和原文，保留用户已有的翻译、笔记、状态。
    解析结果里不存在的旧段落会被清掉，避免库和文件不一致。
    """
    with connect() as conn:
        _write_blocks(conn, doc_id, blocks)


def _write_blocks(conn: sqlite3.Connection, doc_id: str, blocks: list[dict[str, Any]]) -> None:
    existing = {
        row["id"] for row in conn.execute("SELECT id FROM blocks WHERE doc_id = ?", (doc_id,))
    }

    for block in blocks:
        payload = dict(block)
        payload["segments"] = json.dumps(block.get("segments") or [], ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO blocks
                (id, doc_id, page, order_index, kind, x0, y0, x1, y1, text, segments)
            VALUES
                (:id, :doc_id, :page, :order_index, :kind, :x0, :y0, :x1, :y1, :text, :segments)
            ON CONFLICT(id) DO UPDATE SET
                order_index = excluded.order_index,
                kind = excluded.kind,
                x0 = excluded.x0, y0 = excluded.y0,
                x1 = excluded.x1, y1 = excluded.y1,
                text = excluded.text,
                segments = excluded.segments
            """,
            payload,
        )

    # 逐条删除过期段落，而不是拼一个巨大的 NOT IN。几百页的文献能有几千个段落，
    # 拼进 SQL 会撞上 SQLite 的参数个数上限。
    stale = [(block_id,) for block_id in existing - {block["id"] for block in blocks}]
    if stale:
        # 段落没了，挂在它上面的对话和向量也留着没意义，一并清掉，否则成了查不到的孤儿数据。
        conn.executemany("DELETE FROM messages WHERE block_id = ?", stale)
        conn.executemany("DELETE FROM embeddings WHERE block_id = ?", stale)
        conn.executemany("DELETE FROM blocks WHERE id = ?", stale)

    conn.execute(
        "UPDATE documents SET block_count = ? WHERE id = ?",
        (len(blocks), doc_id),
    )


def get_blocks(doc_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        return [
            _to_block(row)
            for row in _rows(
                conn.execute(
                    _BLOCK_SELECT + " WHERE b.doc_id = ? ORDER BY b.order_index", (doc_id,)
                )
            )
        ]


def get_block(block_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(_BLOCK_SELECT + " WHERE b.id = ?", (block_id,)).fetchone()
        return _to_block(dict(row)) if row else None


def list_questions(doc_id: str) -> list[dict[str, Any]]:
    """列出所有留下痕迹的段落，供「疑问清单」回顾。

    只取第一条提问：用户要的是「我当时在哪卡住了」，一条就够定位。
    """
    with connect() as conn:
        return [
            _to_block(row)
            for row in _rows(
                conn.execute(
                    """
                SELECT * FROM (
                    SELECT b.id, b.page, b.order_index, b.kind, b.text, b.note, b.segments,
                           (SELECT COUNT(*) FROM messages m
                             WHERE m.block_id = b.id AND m.role = 'user')
                               AS message_count,
                           (SELECT m.content FROM messages m
                             WHERE m.block_id = b.id AND m.role = 'user'
                             ORDER BY m.id LIMIT 1) AS first_question
                    FROM blocks b
                    WHERE b.doc_id = ?
                )
                WHERE message_count > 0 OR (note IS NOT NULL AND TRIM(note) <> '')
                ORDER BY order_index
                """,
                    (doc_id,),
                )
            )
        ]


def reading_record(doc_id: str) -> list[dict[str, Any]]:
    """这篇文献里留下痕迹的段落，连同它们的完整问答。用于导出。"""
    return [
        {"block": item, "messages": get_messages(doc_id, item["id"])}
        for item in list_questions(doc_id)
    ]


def update_block(block_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"translation", "note"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if updates:
        updates["updated_at"] = now()
        clause = ", ".join(f"{k} = :{k}" for k in updates)
        with connect() as conn:
            conn.execute(
                f"UPDATE blocks SET {clause} WHERE id = :block_id",
                {**updates, "block_id": block_id},
            )
    return get_block(block_id)


# ----------------------------------------------------------------- messages

def add_message(
    doc_id: str,
    block_id: str | None,
    scope: str,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = json.dumps(citations, ensure_ascii=False) if citations else None
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (doc_id, block_id, scope, role, content, citations, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, block_id, scope, role, content, payload, now()),
        )
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _to_message(dict(row))


def get_messages(doc_id: str, block_id: str | None) -> list[dict[str, Any]]:
    with connect() as conn:
        if block_id is None:
            cur = conn.execute(
                "SELECT * FROM messages WHERE doc_id = ? AND block_id IS NULL ORDER BY id",
                (doc_id,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM messages WHERE doc_id = ? AND block_id = ? ORDER BY id",
                (doc_id, block_id),
            )
        return [_to_message(row) for row in _rows(cur)]


def clear_messages(doc_id: str, block_id: str | None) -> None:
    with connect() as conn:
        if block_id is None:
            conn.execute(
                "DELETE FROM messages WHERE doc_id = ? AND block_id IS NULL", (doc_id,)
            )
        else:
            conn.execute(
                "DELETE FROM messages WHERE doc_id = ? AND block_id = ?", (doc_id, block_id)
            )


def _to_message(row: dict[str, Any]) -> dict[str, Any]:
    row["citations"] = json.loads(row["citations"]) if row.get("citations") else []
    return row


# --------------------------------------------------------------- embeddings

def save_embeddings(doc_id: str, model: str, items: list[tuple[str, list[float]]]) -> None:
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO embeddings (block_id, doc_id, model, vector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(block_id) DO UPDATE SET model = excluded.model, vector = excluded.vector
            """,
            [(bid, doc_id, model, json.dumps(vec)) for bid, vec in items],
        )


def get_embeddings(doc_id: str, model: str) -> dict[str, list[float]]:
    with connect() as conn:
        rows = _rows(
            conn.execute(
                "SELECT block_id, vector FROM embeddings WHERE doc_id = ? AND model = ?",
                (doc_id, model),
            )
        )
    return {row["block_id"]: json.loads(row["vector"]) for row in rows}


# ---------------------------------------------------------------- doc notes

def get_doc_note(doc_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT content FROM doc_notes WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return row["content"] if row else ""


def set_doc_note(doc_id: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO doc_notes (doc_id, content, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                content = excluded.content, updated_at = excluded.updated_at
            """,
            (doc_id, content, now()),
        )

