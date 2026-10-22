"""皮肤：一张壁纸加一组参数。

内置皮肤放在 `backend/app/skins/` 里随代码走，只读；用户自己丢进来的图放
`data/skins/<id>/`，删掉整个目录就等于没装过。

每套皮肤的明暗和主色都从图片里算出来，不让人手填色号：一张图丢进来就能直接用。
参数跟着图走，而不是先选色板再配图。
"""
from __future__ import annotations

import colorsys
import json
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from .config import ROOT, settings

BUILTIN_DIR = ROOT / "backend" / "app" / "skins"
MAX_COVER_BYTES = 12 * 1024 * 1024
# 皮肤编号会拼进文件路径和 URL，只允许小写字母、数字和连字符。
SKIN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# 分析壁纸时缩到这么小，几百毫秒内算完，颜色也够用。
SAMPLE_SIZE = 96

# 原味：没有壁纸、面板不透明、不模糊，就是改造前的界面。它是列表里的第一项。
PLAIN: dict[str, Any] = {
    "id": "plain",
    "name": "原味",
    "builtin": True,
    "cover": "",
    "mode": "system",
    "accent": "",
    "palette": [],
    "blur": 0.0,
    "panel_opacity": 1.0,
    "mask": 0.0,
    "wallpaper_blur": 0.0,
    "reader_shade": 0.0,
}


def _user_dir() -> Path:
    path = settings.data_path / "skins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _pick_accent(candidates: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    """挑一个「有颜色」的候选：饱和度够、又不太黑不太白。"""
    for rgb in candidates:
        _hue, saturation, value = colorsys.rgb_to_hsv(*[channel / 255 for channel in rgb])
        if saturation >= 0.22 and 0.25 <= value <= 0.92:
            return rgb
    return candidates[0] if candidates else None


def _fit_contrast(rgb: tuple[int, int, int], mode: str) -> tuple[int, int, int]:
    """把主色往看得清的方向推一把：深色界面里别太暗，浅色界面里别太亮。"""
    hue, saturation, value = colorsys.rgb_to_hsv(*[channel / 255 for channel in rgb])
    if mode == "dark":
        value = max(value, 0.62)
        saturation = min(max(saturation, 0.3), 0.7)
    else:
        value = min(value, 0.58)
        saturation = min(max(saturation, 0.3), 0.75)
    scaled = colorsys.hsv_to_rgb(hue, saturation, value)
    return (round(scaled[0] * 255), round(scaled[1] * 255), round(scaled[2] * 255))


def analyse_image(path: Path) -> dict[str, Any]:
    """从壁纸里读明暗和主色。

    亮度决定界面该用亮字还是暗字；主色取「出现得多、又有颜色」的那一档，
    整张图都是灰的时候退回出现最多的颜色，再按明暗调一下保证能看清。
    """
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.thumbnail((SAMPLE_SIZE, SAMPLE_SIZE))
        pixels = list(image.getdata())

    if not pixels:
        raise ValueError("这张图读不出像素")

    total = len(pixels)
    luminance = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels) / total
    # 每通道压到 4 位再数，免得照片里几万种相近颜色把统计冲散。
    buckets = Counter(
        ((r // 16) * 16 + 8, (g // 16) * 16 + 8, (b // 16) * 16 + 8) for r, g, b in pixels
    )
    top = [rgb for rgb, _count in buckets.most_common(8)]
    mode = "dark" if luminance < 120 else "light"

    accent = _pick_accent(top) or (80, 120, 200)
    return {
        "mode": mode,
        "accent": _hex(_fit_contrast(accent, mode)),
        "palette": [_hex(rgb) for rgb in top[:4]],
    }


def _read_meta(directory: Path, *, builtin: bool) -> dict[str, Any] | None:
    meta_path = directory / "skin.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"皮肤配置不是有效 JSON：{meta_path}") from exc

    skin_id = directory.name
    if not SKIN_ID.fullmatch(skin_id):
        raise ValueError(f"皮肤目录名只能用小写字母、数字和连字符：{skin_id}")
    cover_name = str(meta.get("cover") or "cover.jpg")
    if not (directory / cover_name).exists():
        raise ValueError(f"皮肤缺少壁纸文件：{directory / cover_name}")

    analysed = analyse_image(directory / cover_name)
    return {
        **PLAIN,
        **meta,
        "id": skin_id,
        "builtin": builtin,
        "cover": cover_name,
        # 明暗和主色都允许配置里钉死；没写就按图片算。内置皮肤会写死，
        # 用户自己传的图不写，交给分析结果。
        "mode": str(meta.get("mode") or analysed["mode"]),
        "palette": analysed["palette"],
        "accent": str(meta.get("accent") or analysed["accent"]),
    }


def list_skins() -> list[dict[str, Any]]:
    """原味排第一，然后内置皮肤，最后是用户自己传的。"""
    skins = [dict(PLAIN)]
    directories: list[tuple[Path, bool]] = []
    if BUILTIN_DIR.is_dir():
        directories += [(path, True) for path in sorted(BUILTIN_DIR.iterdir()) if path.is_dir()]
    directories += [(path, False) for path in sorted(_user_dir().iterdir()) if path.is_dir()]

    for directory, builtin in directories:
        try:
            meta = _read_meta(directory, builtin=builtin)
        except ValueError:
            # 单套皮肤坏了（图丢了、JSON 写错了）不该连累整个列表，跳过它就行。
            continue
        if meta:
            skins.append(meta)
    return skins


def get_skin(skin_id: str) -> dict[str, Any] | None:
    if skin_id == "plain":
        return dict(PLAIN)
    if not SKIN_ID.fullmatch(skin_id):
        return None
    for directory, builtin in ((BUILTIN_DIR / skin_id, True), (_user_dir() / skin_id, False)):
        if directory.is_dir():
            return _read_meta(directory, builtin=builtin)
    return None


def cover_path(skin_id: str) -> Path | None:
    if not SKIN_ID.fullmatch(skin_id):
        return None
    for directory in (BUILTIN_DIR / skin_id, _user_dir() / skin_id):
        if not directory.is_dir():
            continue
        cover_name = directory / "skin.json"
        if not cover_name.exists():
            continue
        meta = json.loads(cover_name.read_text(encoding="utf-8"))
        candidate = directory / str(meta.get("cover") or "cover.jpg")
        if candidate.exists():
            return candidate
    return None


def create_skin(name: str, filename: str, payload: bytes) -> dict[str, Any]:
    """把用户丢进来的图存成一套皮肤。"""
    clean = name.strip()[:40] or Path(filename).stem[:40] or "我的皮肤"
    skin_id = f"user-{uuid.uuid4().hex[:8]}"
    directory = _user_dir() / skin_id
    directory.mkdir(parents=True)

    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        suffix = ".jpg"
    cover = directory / f"cover{suffix}"
    cover.write_bytes(payload)

    try:
        analysed = analyse_image(cover)
    except Exception:
        # 不是图片或读不出来，就把刚建好的目录清掉，不留半套皮肤。
        for item in directory.iterdir():
            item.unlink()
        directory.rmdir()
        raise

    meta = {
        "name": clean,
        "cover": cover.name,
        "accent": analysed["accent"],
        # 这些是这套皮肤的默认参数，用户在界面上拖过的数值另外存。
        "blur": 18.0,
        "panel_opacity": 0.62,
        "mask": 0.35 if analysed["mode"] == "dark" else 0.2,
        "wallpaper_blur": 0.0,
        "reader_shade": 0.45 if analysed["mode"] == "dark" else 0.2,
    }
    (directory / "skin.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    created = _read_meta(directory, builtin=False)
    if created is None:
        raise ValueError("皮肤保存失败")
    return created


def delete_skin(skin_id: str) -> None:
    if skin_id == "plain" or not SKIN_ID.fullmatch(skin_id):
        raise ValueError("这套皮肤不能删除")
    directory = _user_dir() / skin_id
    if not directory.is_dir():
        raise ValueError("只能删除自己上传的皮肤")
    for item in directory.iterdir():
        item.unlink()
    directory.rmdir()
