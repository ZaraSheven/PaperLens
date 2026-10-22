"""配置读取。

所有上游模型统一按 OpenAI 兼容接口访问，因此只需要 base_url / api_key / model 三项。
对话模型负责问答和笔记，翻译模型只负责翻译，两者互相独立。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import set_key
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.getenv("PAPER_READER_ENV_FILE", str(ROOT / ".env")))

_ENV_TO_FIELD = {
    "CHAT_BASE_URL": "chat_base_url",
    "CHAT_API_KEY": "chat_api_key",
    "CHAT_MODEL": "chat_model",
    "CHAT_VISION": "chat_vision",
    "TRANSLATE_BASE_URL": "translate_base_url",
    "TRANSLATE_API_KEY": "translate_api_key",
    "TRANSLATE_MODEL": "translate_model",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    chat_base_url: str = ""
    chat_api_key: str = ""
    chat_model: str = ""
    # 对话模型能不能看图。开着的话，问图、公式、表格时会把它那一块的原图
    # 一起发给模型；模型不支持图片时请求会直接报错，那就关掉。
    chat_vision: bool = True

    translate_base_url: str = ""
    translate_api_key: str = ""
    translate_model: str = ""

    host: str = "127.0.0.1"
    port: int = 8756
    data_dir: str = "data"

    @property
    def data_path(self) -> Path:
        path = ROOT / self.data_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def translation_route(self) -> tuple[str, str, str]:
        """翻译走哪套配置。

        翻译模型和对话模型分开：翻译模型必须单独配置三项，不能偷偷复用对话模型。
        """
        filled = (
            bool(self.translate_base_url),
            bool(self.translate_api_key),
            bool(self.translate_model),
        )
        if not all(filled):
            raise ValueError("翻译模型的 base_url / api_key / model 三项都必填")
        return (self.translate_base_url, self.translate_api_key, self.translate_model)


settings = Settings()


def save_settings(updates: dict[str, str]) -> None:
    """写入 .env，并立即更新内存里的配置，不要求重启服务。"""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.touch(exist_ok=True)
    for key, value in updates.items():
        set_key(str(ENV_FILE), key, value, quote_mode="always")
        field = _ENV_TO_FIELD[key]
        current = getattr(settings, field)
        # 布尔字段要按布尔写回内存：直接塞字符串的话，"0" 也是真值。
        if isinstance(current, bool):
            setattr(settings, field, value.strip().lower() in {"1", "true", "yes", "on"})
        else:
            setattr(settings, field, value)

