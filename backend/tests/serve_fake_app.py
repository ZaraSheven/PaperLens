"""用假模型起一个临时实例，专门用来跑界面自检。

界面自检里有一处真的会调用对话模型。上游模型掉线、欠费、没通道的时候，自检就会红一片，
看起来像是界面坏了。这个脚本起一个「模型永远是假的」实例：用户自己的 .env 和 data/
一律不动，数据和配置都落在临时目录里。

运行：.venv\\Scripts\\python.exe backend\\tests\\serve_fake_app.py --port 8765
然后：cd frontend; $env:APP_URL="http://127.0.0.1:8765"; node scripts/verify_ui.mjs
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parents[1]
REAL_DATA = ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="假模型 + 临时数据目录，用来跑界面自检")
    parser.add_argument("--port", type=int, default=8765, help="应用监听端口")
    parser.add_argument("--model-port", type=int, default=8899, help="假模型监听端口")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="paperlens-verify-"))
    if (REAL_DATA / "library.db").exists():
        shutil.copy(REAL_DATA / "library.db", work / "library.db")
        for pdf in REAL_DATA.glob("*.pdf"):
            shutil.copy(pdf, work / pdf.name)

    # settings 是导入 app 时读环境变量的，所以这些必须在 uvicorn 导入应用之前设好。
    os.environ.update(
        {
            "DATA_DIR": str(work),
            "PAPER_READER_ENV_FILE": str(work / "config.env"),
            "CHAT_BASE_URL": f"http://127.0.0.1:{args.model_port}/v1",
            "CHAT_API_KEY": "fake-key",
            "CHAT_MODEL": "fake-chat",
            "TRANSLATE_BASE_URL": f"http://127.0.0.1:{args.model_port}/v1",
            "TRANSLATE_API_KEY": "fake-key",
            "TRANSLATE_MODEL": "fake-translate",
            "SKIP_CONNECTION_TEST": "1",
        }
    )

    sys.path.insert(0, str(TESTS_DIR))
    sys.path.insert(0, str(ROOT / "backend"))

    import fake_llm  # noqa: E402
    import uvicorn  # noqa: E402

    fake_llm.start(args.model_port)
    print(f"假模型在 {args.model_port}；临时数据目录 {work}", flush=True)
    print(f"应用起在 http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, app_dir=str(ROOT / "backend"))


if __name__ == "__main__":
    main()
