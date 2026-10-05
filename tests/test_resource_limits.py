"""Resource caps, corrupt input and unsupported formats."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from visual_regression.config import CompareConfig, ResourceLimits
from visual_regression.errors import (
    DimensionMismatchError,
    ImageTooLargeError,
    InvalidInputError,
    UnsupportedFormatError,
)
from visual_regression.imaging import decode_image
from visual_regression.comparator import run_comparison

from .conftest import make_png


def test_oversize_pixels_rejected():
    limits = ResourceLimits(max_pixels=100, max_width=1000, max_height=1000)
    png = make_png(size=(12, 12))
    with pytest.raises(ImageTooLargeError) as exc:
        decode_image(png, limits)
    assert "pixels" in str(exc.value)


def test_oversize_dimension_rejected():
    limits = ResourceLimits(max_pixels=10000, max_width=8, max_height=100)
    with pytest.raises(ImageTooLargeError):
        decode_image(make_png(size=(9, 5)), limits)


def test_oversize_encoded_bytes_rejected():
    limits = ResourceLimits(max_bytes=10)
    with pytest.raises(ImageTooLargeError):
        decode_image(make_png(size=(32, 32)), limits)


def test_empty_and_corrupt_payload_rejected():
    limits = ResourceLimits()
    with pytest.raises(InvalidInputError):
        decode_image(b"", limits)
    with pytest.raises(InvalidInputError):
        decode_image(b"definitely not an image", limits)


def test_truncated_png_rejected():
    png = make_png(size=(16, 16))
    limits = ResourceLimits()
    with pytest.raises(InvalidInputError):
        decode_image(png[: len(png) // 2], limits)


def test_unsupported_format_rejected():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, "BMP")
    limits = ResourceLimits()
    with pytest.raises(UnsupportedFormatError):
        decode_image(buf.getvalue(), limits)


def test_dimension_mismatch_is_distinct_error():
    limits = ResourceLimits()
    with pytest.raises(DimensionMismatchError):
        run_comparison(
            "c",
            make_png(size=(8, 8)),
            make_png(size=(9, 8)),
            CompareConfig(),
            limits,
        )


def test_batch_budget_enforced(service):
    # each image is 40x40 = 1600 pixels; budget is 8,000,000 in this fixture,
    # shrink via a fresh service:
    from visual_regression.service import VisualRegressionService

    small = VisualRegressionService(
        limits=ResourceLimits(max_pixels=1_000_000, pixel_budget=2000)
    )
    small.compare_case("seed", make_png(size=(40, 40)))
    summary = small.run_batch(
        [{"case_id": "seed", "candidate": make_png(size=(40, 40))} for _ in range(3)]
    )
    # first image passes (1600), second pushes to 3200 > 2000 -> failed;
    # isolation keeps subsequent items running (they fail too on budget)
    assert summary.total == 3
    assert summary.failed >= 1
    assert any(i.error_code == "image_too_large" for i in summary.items)
