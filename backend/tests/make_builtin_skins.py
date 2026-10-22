"""生成三套内置壁纸。

运行：.venv\\Scripts\\python.exe backend\\tests\\make_builtin_skins.py

内置皮肤只是「能立刻用」的样例，重点在皮肤引擎：拖自己的图进来就能成套。
壁纸用 Pillow 现画（多层柔光和颗粒），不依赖任何画图服务，重跑一次结果一致。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backend" / "app" / "skins"
WIDTH, HEIGHT = 2560, 1440


def bokeh(
    colors: list[tuple[int, int, int]], rng: random.Random, count: int, blur_scale: float
) -> Image.Image:
    """散景光斑。圆越大越虚，边上留一圈更亮的边，像失焦的灯。"""
    layer = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    for _ in range(count):
        radius = rng.randint(WIDTH // 22, WIDTH // 9)
        cx = rng.randint(-radius, WIDTH + radius)
        cy = rng.randint(-radius, HEIGHT + radius)
        color = rng.choice(colors)
        ring = tuple(min(255, int(channel * 1.25) + 24) for channel in color)
        draw = ImageDraw.Draw(layer)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius), outline=ring, width=radius // 7
        )
    return layer.filter(ImageFilter.GaussianBlur(blur_scale))


def dreamscape(colors: list[tuple[int, int, int]], seed: int, grain: int = 8) -> Image.Image:
    """把几个颜色揉成一张柔和的云雾壁纸。

    先在很小的网格上撒颜色，再放大插值，得到没有硬边的大色块；然后叠十几团柔光，
    最后加颗粒和暗角。这样出来的图柔、不成块，做背景不会跟正文抢注意力。
    """
    rng = random.Random(seed)

    grid = Image.new("RGB", (7, 4))
    cells = grid.load()
    for y in range(4):
        for x in range(7):
            cells[x, y] = rng.choice(colors)
    canvas = grid.resize((WIDTH // 16, HEIGHT // 16), Image.BICUBIC).resize(
        (WIDTH, HEIGHT), Image.BICUBIC
    )

    # 先铺散景，再压大团柔光：光斑被柔光吃掉一半，看着是「失焦的远处」，不是贴纸。
    spots = bokeh(colors, rng, count=14, blur_scale=WIDTH / 90)
    canvas = ImageChops.screen(canvas, spots.point(lambda value: int(value * 0.42)))

    for _ in range(16):
        layer = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(layer)
        radius = rng.randint(WIDTH // 8, WIDTH // 3)
        cx = rng.randint(-radius // 2, WIDTH + radius // 2)
        cy = rng.randint(-radius // 2, HEIGHT + radius // 2)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=rng.choice(colors))
        layer = layer.filter(ImageFilter.GaussianBlur(radius / 2.4))
        canvas = ImageChops.screen(canvas, layer.point(lambda value: int(value * 0.5)))

    if grain:
        noise = Image.effect_noise((WIDTH, HEIGHT), grain).convert("L")
        canvas = ImageChops.add(canvas, Image.merge("RGB", (noise, noise, noise)), scale=1.6)

    # 暗角：四角压暗一点点，中间那圈留亮，界面上的卡片才压得住。
    vignette = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(vignette).ellipse(
        (-WIDTH // 3, -HEIGHT // 3, WIDTH + WIDTH // 3, HEIGHT + HEIGHT // 3), fill=255
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(WIDTH / 10)).point(
        lambda value: 150 + value * 105 // 255
    )
    return Image.composite(canvas, canvas.point(lambda value: int(value * 0.78)), vignette)


SKINS = [
    {
        "id": "rose-dream",
        "meta": {
            "name": "暖粉梦境",
            "cover": "cover.jpg",
            "mode": "light",
            "accent": "#c86b93",
            "blur": 20,
            "panel_opacity": 0.62,
            "mask": 0.12,
            "wallpaper_blur": 0,
            "reader_shade": 0.1,
        },
        "colors": [
            (250, 233, 236),
            (240, 205, 219),
            (214, 176, 205),
            (198, 173, 214),
            (255, 246, 240),
            (232, 190, 178),
        ],
        "seed": 20261022,
    },
    {
        "id": "ink-night",
        "meta": {
            "name": "墨蓝夜航",
            "cover": "cover.jpg",
            "mode": "dark",
            "accent": "#66b3c9",
            "blur": 22,
            "panel_opacity": 0.55,
            "mask": 0.2,
            "wallpaper_blur": 0,
            "reader_shade": 0.42,
        },
        "colors": [
            (14, 22, 44),
            (24, 42, 76),
            (18, 60, 84),
            (34, 28, 64),
            (52, 86, 124),
            (10, 16, 30),
        ],
        "seed": 771,
    },
    {
        "id": "paper-calm",
        "meta": {
            "name": "素纸",
            "cover": "cover.jpg",
            "mode": "light",
            "accent": "#3f5d7d",
            "blur": 16,
            "panel_opacity": 0.78,
            "mask": 0.05,
            "wallpaper_blur": 0,
            "reader_shade": 0.06,
        },
        "colors": [
            (248, 246, 242),
            (231, 229, 223),
            (214, 218, 224),
            (245, 240, 232),
            (224, 228, 234),
            (203, 209, 218),
        ],
        "seed": 5150,
    },
    {
        "id": "moss-calm",
        "meta": {
            "name": "苔原绿",
            "cover": "cover.jpg",
            "mode": "light",
            "accent": "#4a7c59",
            "blur": 18,
            "panel_opacity": 0.7,
            "mask": 0.1,
            "wallpaper_blur": 0,
            "reader_shade": 0.08,
        },
        "colors": [
            (238, 244, 230),
            (208, 224, 198),
            (178, 204, 176),
            (148, 180, 150),
            (245, 249, 240),
            (196, 216, 188),
        ],
        "seed": 8412,
    },
    {
        "id": "amber-dusk",
        "meta": {
            "name": "琥珀黄昏",
            "cover": "cover.jpg",
            "mode": "dark",
            "accent": "#d9903f",
            "blur": 22,
            "panel_opacity": 0.55,
            "mask": 0.22,
            "wallpaper_blur": 0,
            "reader_shade": 0.45,
        },
        "colors": [
            (48, 30, 20),
            (88, 50, 28),
            (124, 74, 36),
            (62, 38, 26),
            (152, 98, 46),
            (32, 22, 16),
        ],
        "seed": 3312,
    },
    {
        "id": "violet-night",
        "meta": {
            "name": "紫罗兰夜",
            "cover": "cover.jpg",
            "mode": "dark",
            "accent": "#a97ce0",
            "blur": 22,
            "panel_opacity": 0.55,
            "mask": 0.2,
            "wallpaper_blur": 0,
            "reader_shade": 0.45,
        },
        "colors": [
            (30, 20, 46),
            (54, 34, 80),
            (40, 26, 60),
            (74, 46, 106),
            (22, 16, 36),
            (98, 66, 134),
        ],
        "seed": 2207,
    },
    {
        "id": "graphite",
        "meta": {
            "name": "石墨",
            "cover": "cover.jpg",
            "mode": "dark",
            "accent": "#7f9bb5",
            "blur": 16,
            "panel_opacity": 0.62,
            "mask": 0.15,
            "wallpaper_blur": 0,
            "reader_shade": 0.35,
        },
        "colors": [
            (26, 27, 30),
            (38, 40, 44),
            (50, 52, 57),
            (20, 21, 24),
            (64, 66, 72),
            (30, 32, 36),
        ],
        "seed": 6601,
    },
]


def main() -> None:
    for item in SKINS:
        directory = OUT_DIR / item["id"]
        directory.mkdir(parents=True, exist_ok=True)
        image = dreamscape(item["colors"], item["seed"])
        cover = directory / item["meta"]["cover"]
        image.save(cover, "JPEG", quality=88, optimize=True)
        (directory / "skin.json").write_text(
            json.dumps(item["meta"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{item['id']}: {cover.relative_to(ROOT)} ({cover.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
