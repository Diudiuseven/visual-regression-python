"""Ignore region validation and masking semantics."""
from __future__ import annotations

import pytest

from visual_regression.config import CompareConfig, ResourceLimits
from visual_regression.diffing import compute_diff
from visual_regression.errors import IgnoreRegionError
from visual_regression.imaging import decode_image
from visual_regression.regions import build_ignore_mask, parse_regions

from .conftest import image_png, solid, with_pixels

LIMITS = ResourceLimits()


def test_valid_region_parses():
    regions = parse_regions([{"x": 1, "y": 2, "width": 3, "height": 4}], 10, 10)
    assert regions[0].x == 1
    assert sum(build_ignore_mask(regions, 10, 10)) == 12


def test_region_out_of_bounds_names_index():
    with pytest.raises(IgnoreRegionError) as exc:
        parse_regions(
            [
                {"x": 0, "y": 0, "width": 2, "height": 2},
                {"x": 8, "y": 8, "width": 4, "height": 4},
            ],
            10,
            10,
        )
    assert exc.value.index == 1
    assert "ignore_regions[1]" in str(exc.value)
    assert "exceeds image bounds" in str(exc.value)


def test_negative_origin_rejected():
    with pytest.raises(IgnoreRegionError) as exc:
        parse_regions([{"x": -1, "y": 0, "width": 1, "height": 1}], 5, 5)
    assert exc.value.index == 0


def test_zero_or_negative_size_rejected():
    for bad in (0, -3):
        with pytest.raises(IgnoreRegionError):
            parse_regions([{"x": 0, "y": 0, "width": bad, "height": 1}], 5, 5)


def test_non_integer_and_missing_keys_rejected():
    with pytest.raises(IgnoreRegionError):
        parse_regions([{"x": 0, "y": 0, "width": 1.5, "height": 1}], 5, 5)
    with pytest.raises(IgnoreRegionError):
        parse_regions([{"x": 0, "y": 0, "width": 1}], 5, 5)
    with pytest.raises(IgnoreRegionError):
        parse_regions("not-a-list", 5, 5)


def test_region_on_boundary_is_allowed():
    # rectangle ending exactly at the image edge is in bounds
    regions = parse_regions([{"x": 8, "y": 8, "width": 2, "height": 2}], 10, 10)
    assert regions[0].width == 2


def test_changes_inside_ignored_region_do_not_count():
    base = solid((0, 0, 0), (10, 10))
    cand = with_pixels((0, 0, 0), (10, 10), [
        ((x, y), (255, 255, 255)) for x in range(2, 5) for y in range(2, 5)
    ])
    a = decode_image(image_png(base), LIMITS)
    b = decode_image(image_png(cand), LIMITS)
    regions = parse_regions([{"x": 0, "y": 0, "width": 10, "height": 10}], 10, 10)
    r = compute_diff(a, b, CompareConfig(change_ratio=0.0), regions)
    assert r.changed_pixels == 0
    assert r.ignored_pixels == 100
    assert r.considered_pixels == 0
    assert r.changed is False


def test_changes_partially_inside_region_count_only_outside():
    base = solid((0, 0, 0), (10, 10))
    cand = solid((0, 0, 0), (10, 10))
    # patch spanning columns 4..7, rows 4..5 (8 pixels); ignore columns 0..5
    for x in range(4, 8):
        for y in range(4, 6):
            cand.putpixel((x, y), (255, 255, 255))
    a = decode_image(image_png(base), LIMITS)
    b = decode_image(image_png(cand), LIMITS)
    regions = parse_regions([{"x": 0, "y": 0, "width": 6, "height": 10}], 10, 10)
    r = compute_diff(a, b, CompareConfig(change_ratio=0.0), regions)
    # only columns 6,7 survive: 2 cols * 2 rows = 4 pixels
    assert r.changed_pixels == 4
    assert r.ignored_pixels == 60
