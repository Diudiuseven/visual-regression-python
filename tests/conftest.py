"""Shared pytest fixtures: in-process generated sample images."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from visual_regression.config import CompareConfig, ResourceLimits
from visual_regression.service import VisualRegressionService


@pytest.fixture
def service() -> VisualRegressionService:
    return VisualRegressionService(
        limits=ResourceLimits(max_pixels=1_000_000, pixel_budget=8_000_000)
    )


@pytest.fixture
def config() -> CompareConfig:
    return CompareConfig()


def make_png(color=(0, 0, 0), size=(16, 16), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def image_png(pixels: Image.Image) -> bytes:
    buf = io.BytesIO()
    pixels.save(buf, "PNG")
    return buf.getvalue()


def solid(color, size=(16, 16)) -> Image.Image:
    return Image.new("RGB", size, color)


def with_pixels(color, size, points) -> Image.Image:
    img = Image.new("RGB", size, color)
    for point, value in points:
        img.putpixel(point, value)
    return img


@pytest.fixture
def png_factory():
    return make_png
