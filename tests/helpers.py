"""测试辅助：进程内生成样本图。"""

from __future__ import annotations

import io

from PIL import Image


def make_png(color: tuple[int, int, int], size: tuple[int, int] = (16, 16)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def paint(img_bytes: bytes, pixels: dict[tuple[int, int], tuple[int, int, int]]) -> bytes:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    for (x, y), c in pixels.items():
        img.putpixel((x, y), c)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def fill_rect(
    img_bytes: bytes,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
) -> bytes:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            img.putpixel((xx, yy), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
