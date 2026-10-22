"""模型链路自检：用假模型服务把翻译、问答、整理笔记整条路跑一遍。

不需要真实 API key。它验证的是「请求怎么拼、消息怎么落库、引用怎么回传」，
不是模型答得好不好。运行：

    .venv\\Scripts\\python.exe backend\\tests\\test_llm_flow.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parents[1]
SAMPLE = ROOT / "samples" / "sample-paper.pdf"
DOC_ID = "fedcba9876543210"
QUESTION = "这篇论文的核心贡献是什么"

# 必须在导入 app 之前把配置塞进环境变量：settings 是在导入时读取的。
# 数据目录也换到临时目录，免得污染真实文献库。
WORK_DIR = tempfile.mkdtemp(prefix="paper-lens-llm-")
CONFIG_FILE = Path(WORK_DIR) / "config.env"
AGENT_FILE = Path(WORK_DIR) / "agent.md"
os.environ.update(
    {
        "DATA_DIR": WORK_DIR,
        "PAPER_READER_ENV_FILE": str(CONFIG_FILE),
        "CHAT_BASE_URL": "http://127.0.0.1:8901/v1",
        "CHAT_API_KEY": "fake-key",
        "CHAT_MODEL": "fake-chat",
        "TRANSLATE_BASE_URL": "http://127.0.0.1:8901/v1",
        "TRANSLATE_API_KEY": "fake-key",
        "TRANSLATE_MODEL": "fake-translate",
    }
)

sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(ROOT / "backend"))

import fake_llm  # noqa: E402
from app import db, llm, main, parser  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    if ok:
        print(f"  通过  {label}")
    else:
        failures.append(label)
        print(f"  失败  {label} {extra}")


def chat_calls() -> list[dict[str, Any]]:
    return [record for record in fake_llm.RECEIVED if "messages" in record]


def last_message_content() -> Any:
    """最近一次对话请求里最后一条消息的 content：可能是纯文字，也可能是「文字 + 图片」数组。"""
    return chat_calls()[0]["messages"][-1]["content"]


def has_image_part() -> bool:
    content = last_message_content()
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in content
    )


def main_() -> int:
    fake_llm.start(8901)

    if not SAMPLE.exists():
        print(f"缺少样例论文 {SAMPLE}，先运行 backend/tests/make_sample.py")
        return 1

    db.init_db()
    # 应用上传 PDF 时会把它落在 data 目录里；问图要从那里裁原图，这里照着摆一份。
    shutil.copy(SAMPLE, llm.settings.data_path / f"{DOC_ID}.pdf")
    config = main.put_config(
        main.ConfigRequest(
            chat=main.ModelRoute(
                base_url="http://127.0.0.1:8901/v1",
                api_key="fake-key",
                model="fake-chat",
            ),
            translate=main.ModelRoute(
                base_url="http://127.0.0.1:8901/v1",
                api_key="fake-key",
                model="fake-translate",
            ),
            note_template="自定义模板：\n{原文}\n{dialogue}".replace("{dialogue}", "{问答}"),
            agent_prompt="回答时先给结论，再给三条关键依据。",
            chat_vision=True,
        )
    )
    check("配置接口能保存模型设置", CONFIG_FILE.exists(), str(CONFIG_FILE))
    check("看图开关进了配置接口", config["config"]["chat_vision"] is True, str(config["config"]))
    check("保存后健康检查显示模型已配置", all(config["health"].values()), str(config["health"]))
    model_list = main.get_model_list(
        main.ModelListRequest(kind="chat", base_url="http://127.0.0.1:8901/v1")
    )
    check(
        "模型列表能从上游拉取",
        {"fake-chat", "fake-translate"}.issubset(set(model_list["models"])),
        str(model_list),
    )
    check(
        "笔记模板保存成功",
        db.get_setting("note_template", "").startswith("自定义模板"),
        db.get_setting("note_template", ""),
    )
    check("agent.md 保存成功", AGENT_FILE.exists(), str(AGENT_FILE))
    check(
        "配置接口返回 agent.md 内容",
        "先给结论" in config["config"]["agent_prompt"],
        str(config["config"]),
    )

    blocks, meta = parser.extract_blocks(str(SAMPLE), DOC_ID)
    db.save_document(
        DOC_ID,
        SAMPLE.name,
        meta["title"],
        meta["page_count"],
        [{"doc_id": DOC_ID, **block} for block in blocks],
    )

    target = next(b for b in blocks if b["kind"] == "text" and len(b["text"]) > 60)

    print("翻译")
    fake_llm.RECEIVED.clear()
    translated = main.translate_block(target["id"])
    check("翻译拿到了结果", bool(translated["translation"]), str(translated["translation"])[:40])
    check("翻译走的是翻译模型", len(chat_calls()) == 1 and chat_calls()[0]["model"] == "fake-translate")
    check(
        "翻译结果写回了库",
        db.get_block(target["id"])["translation"] == translated["translation"],
    )

    print("\n问答：整篇找依据 + 锚点那一段")
    fake_llm.RECEIVED.clear()
    answer = main.ask_about_block(target["id"], main.AskRequest(content=QUESTION))
    check("返回了回答", bool(answer["message"]["content"]), str(answer["message"])[:60])
    check("回答落库成了 assistant 消息", answer["message"]["role"] == "assistant")
    check("带回了引用", len(answer["citations"]) > 0, str(len(answer["citations"])))
    check("引用带页码", all("page" in item for item in answer["citations"]))
    check(
        "段落有了疑问标记",
        answer["block"]["message_count"] == 1,
        str(answer["block"]),
    )

    messages = db.get_messages(DOC_ID, target["id"])
    check("一问一答各存一条", len(messages) == 2, str([m["role"] for m in messages]))
    check("顺序是先问后答", [m["role"] for m in messages] == ["user", "assistant"])

    sent = [m["content"] for m in chat_calls()[0]["messages"]]
    check(
        "同一个问题只送给模型一次",
        sum(1 for content in sent if QUESTION in content) == 1,
        str(sum(1 for content in sent if QUESTION in content)),
    )
    check("模型收到了原文片段", any("原文片段" in content for content in sent))
    check("全文问答不调用额外向量模型", not any("input" in record for record in fake_llm.RECEIVED))
    check(
        "agent.md 进入了系统提示",
        any("用户自定义 Agent 设定" in content and "先给结论" in content for content in sent),
        str(sent),
    )
    check(
        "提示词要求不输出引用编号",
        any("不要输出引用编号" in content for content in sent),
        str(sent),
    )

    print("\n状态与分类")
    updated = main.patch_document(
        DOC_ID,
        main.DocumentPatch(read_status="read", category="测试分类"),
    )
    check("文献可以标记已读", updated["read_status"] == "read", str(updated))
    check("文献可以设置分类", updated["category"] == "测试分类", str(updated))
    categories = main.create_category(main.CategoryRequest(name="综述"))
    check("可以新增分类", "综述" in categories["categories"], str(categories))

    print("\n文献详情")
    overview = main.get_document_overview(DOC_ID)
    check("详情包含论文梗概", bool(overview["overview"]["summary"]), str(overview["overview"]))
    check("详情包含方法列表", bool(overview["overview"]["methods"]), str(overview["overview"]))
    check("详情包含自己的问答", len(overview["questions"]) > 0, str(len(overview["questions"])))

    print("\n同一段的追问")
    fake_llm.RECEIVED.clear()
    second = main.ask_about_block(target["id"], main.AskRequest(content="这段的公式在说什么"))
    check("再问一次也能回答", bool(second["message"]["content"]))
    check("问答不走向量检索", not any("input" in record for record in fake_llm.RECEIVED))
    check("一次提问只调一次对话模型", len(chat_calls()) == 1, str(len(chat_calls())))
    check("对话累计到四条", len(db.get_messages(DOC_ID, target["id"])) == 4)

    print("\n问图和公式")
    # 样张里没有图块，手工放一块空文字的图进库——这正是用户点开图提问的情形：
    # 图里一个字都抽不到，以前会被当成空段落丢掉，模型只能回答「原文没有提及」。
    figure = {
        "id": "figure0000000000001",
        "doc_id": DOC_ID,
        "page": 0,
        "order_index": max(b["order_index"] for b in blocks) + 1,
        "kind": "figure",
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.5,
        "y1": 0.5,
        "text": "",
        "segments": [],
    }
    db.save_blocks(DOC_ID, [{"doc_id": DOC_ID, **b} for b in blocks] + [figure])
    check("空文字的图块能落库", db.get_block(figure["id"])["kind"] == "figure")

    fake_llm.RECEIVED.clear()
    asked_figure = main.ask_about_block(
        figure["id"], main.AskRequest(content="这幅图讲了什么")
    )
    figure_system = "\n".join(
        item["content"] for item in chat_calls()[0]["messages"] if item["role"] == "system"
    )
    check("图块也能拿到回答", bool(asked_figure["message"]["content"]))
    check("问图时把那一块的原图一起发给了模型", has_image_part(), str(last_message_content())[:120])
    check("上下文中标出了这是一张图", "· 图)" in figure_system, figure_system[:240])
    check(
        "上下文中说明图里没抽出文字",
        "图里的文字没有抽出来" in figure_system,
        figure_system[:240],
    )
    check(
        "系统提示要求不要凭空描述图里画了什么",
        "不要凭空描述图里画了什么" in figure_system,
        figure_system[:240],
    )

    # 模型不支持图片时用户可以关掉这个开关，关掉之后就不该再发图。
    llm.settings.chat_vision = False
    try:
        fake_llm.RECEIVED.clear()
        main.ask_about_block(figure["id"], main.AskRequest(content="再解释一次"))
        check("关掉看图开关后不再发原图", not has_image_part(), str(last_message_content())[:120])
    finally:
        llm.settings.chat_vision = True

    # 整篇对话面板里没有锚点，就纯靠关键词检索；这类问题不该被算成「点着某一段问的」。
    fake_llm.RECEIVED.clear()
    main.ask_about_document(DOC_ID, main.AskRequest(content="这篇的贡献是什么"))
    doc_system = "\n".join(
        item["content"] for item in chat_calls()[0]["messages"] if item["role"] == "system"
    )
    check("整篇提问拿得到原文片段", "原文片段" in doc_system, doc_system[:240])
    check(
        "整篇提问不带图块这类锚点说明",
        "· 图)" not in doc_system,
        doc_system[:240],
    )
    doc_messages = db.get_messages(DOC_ID, None)
    check(
        "整篇提问记成 full",
        all(message["scope"] == "full" for message in doc_messages),
        str([message["scope"] for message in doc_messages]),
    )

    print("\n流式问答")
    with TestClient(main.app) as client:
        with client.stream(
            "POST",
            f"/api/blocks/{figure['id']}/messages/stream",
            json={"content": "流式问一次"},
        ) as response:
            check("流式接口返回 200", response.status_code == 200, str(response.status_code))
            check(
                "返回的是事件流",
                response.headers.get("content-type", "").startswith("text/event-stream"),
                response.headers.get("content-type", ""),
            )
            lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    events = [json.loads(line[6:]) for line in lines]
    check(
        "回答分成多段推过来",
        sum(1 for event in events if event["type"] == "delta") >= 2,
        str(events[:3]),
    )
    check("最后一条事件是完成", events[-1]["type"] == "done", str(events[-1]))
    streamed = db.get_messages(DOC_ID, figure["id"])[-2:]
    check(
        "问题在流式回答之前就落了库",
        streamed[0]["role"] == "user" and streamed[0]["content"] == "流式问一次",
        str(streamed[0]),
    )
    check(
        "流式回答整条落了库",
        streamed[1]["role"] == "assistant" and bool(streamed[1]["content"]),
        str(streamed[1])[:80],
    )

    print("\n整理笔记")
    noted = main.generate_block_note(target["id"])
    check("笔记生成成功", bool(noted["note"]), str(noted["note"])[:40])
    check("笔记计入留痕标记", noted["has_note"] == 1)

    print("\n疑问清单")
    questions = db.list_questions(DOC_ID)
    check("清单里有这一段", any(item["id"] == target["id"] for item in questions))
    check(
        "清单带上了我提的第一个问题",
        any(item["first_question"] == QUESTION for item in questions),
    )
    check(
        "清单里的次数是两次",
        any(item["id"] == target["id"] and item["message_count"] == 2 for item in questions),
        str(questions),
    )

    print("\n导出 Markdown")
    exported = main.export_markdown(DOC_ID)
    body = exported.body.decode("utf-8")
    check("导出以文献标题开头", body.startswith("# "), body[:40])
    check("导出里有我提的问题", QUESTION in body)
    check("导出里有助手的回答", "假回答" in body)
    check("导出里有笔记小节", "**笔记**" in body)
    check(
        "导出带上文件名",
        "attachment" in exported.headers["content-disposition"],
        exported.headers["content-disposition"],
    )

    print("\n配置缺失时的行为")
    saved_key = llm.settings.chat_api_key
    llm.settings.chat_api_key = ""
    try:
        llm.chat([{"role": "user", "content": "在吗"}])
        check("缺配置时应当报错", False, "没有抛异常")
    except llm.ConfigError as error:
        check("缺配置时抛出明确错误", "未配置" in str(error), str(error))
    finally:
        llm.settings.chat_api_key = saved_key

    print()
    if failures:
        print(f"失败 {len(failures)} 项：" + "；".join(failures))
        return 1
    print("模型链路自检全部通过")
    return 0


if __name__ == "__main__":
    try:
        code = main_()
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    sys.exit(code)
