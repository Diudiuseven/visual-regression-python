"""JPEG inputs and alpha-channel flattening."""
from __future__ import annotations

import io

from PIL import Image

from visual_regression.config import ResourceLimits
from visual_regression.imaging import decode_image
from visual_regression.service import ItemStatus

from .conftest import make_png

LIMITS = ResourceLimits()


def test_jpeg_input_is_accepted(service):
    a = Image.new("RGB", (16, 16), (10, 20, 30))
    b = Image.new("RGB", (16, 16), (200, 30, 30))

    def jpeg(im):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=95)
        return buf.getvalue()

    service.compare_case("j", jpeg(a))
    r = service.compare_case("j", jpeg(b))
    assert r.status in (ItemStatus.DIFF, ItemStatus.NO_DIFF)
    assert r.status == ItemStatus.DIFF  # strong color change survives JPEG noise


def test_transparent_pixels_flatten_onto_black():
    # fully transparent pixel over black matte equals opaque black
    im = Image.new("RGBA", (4, 4), (200, 200, 200, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    decoded = decode_image(buf.getvalue(), LIMITS)
    assert decoded.rgb[:3] == bytes((0, 0, 0))


def test_opaque_rgba_keeps_its_color():
    im = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    decoded = decode_image(buf.getvalue(), LIMITS)
    assert decoded.rgb[:3] == bytes((10, 20, 30))


def test_alpha_and_opaque_black_compare_equal(service):
    transparent = io.BytesIO()
    Image.new("RGBA", (8, 8), (5, 6, 7, 0)).save(transparent, "PNG")
    black = make_png((0, 0, 0), (8, 8))
    service.compare_case("a", transparent.getvalue())
    r = service.compare_case("a", black)
    assert r.status == ItemStatus.NO_DIFF
    assert r.summary["changed_pixels"] == 0
