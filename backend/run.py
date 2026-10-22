"""启动开发服务器：.venv\\Scripts\\python.exe backend\\run.py"""
from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)

