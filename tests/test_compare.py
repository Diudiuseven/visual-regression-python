"""对比判定：阈值边界、忽略区域、容忍度、确定性、资源上限与错误分类。"""

from __future__ import annotations

import pytest

from visual_regression import (
    CompareConfig,
    DimensionMismatchError,
    IgnoreRegionError,
    ImageDecodeError,
    Region,
    ResourceLimitError,
    Verdict,
    compare_images,
)

from .helpers import fill_rect, make_png, paint

BASE = (100, 150, 200)


class TestVerdict:
    def test_identical_is_unchanged(self):
        a = make_png(BASE)
        r = compare_images(a, a)
        assert r.verdict is Verdict.UNCHANGED
        assert not r.changed
        assert r.changed_pixels == 0
        assert r.changed_ratio == 0.0

    def test_single_pixel_change_is_changed_by_default(self):
        a = make_png(BASE)
        b = paint(a, {(5, 5): (0, 0, 0)})
        r = compare_images(a, b)
        assert r.verdict is Verdict.CHANGED
        assert r.changed
        assert r.changed_pixels == 1
        assert r.changed_ratio == pytest.approx(1 / 256)
        assert r.effective_pixels == 256

    def test_diff_image_is_valid_png_and_marks_change(self):
        a = make_png(BASE)
        b = paint(a, {(5, 5): (0, 0, 0)})
        r = compare_images(a, b)
        assert r.diff_image[:8] == b"\x89PNG\r\n\x1a\n"


class TestThresholdBoundaries:
    def test_pixel_threshold_boundary(self):
        a = make_png(BASE)
        b = paint(a, {(1, 1): (0, 0, 0), (2, 2): (0, 0, 0)})
        # 变化数等于阈值：未超过，判通过（within_threshold）
        r = compare_images(a, b, CompareConfig(pixel_threshold=2, changed_ratio_threshold=1.0))
        assert r.verdict is Verdict.WITHIN_THRESHOLD
        assert not r.changed
        # 阈值减一：超过，判变化
        r = compare_images(a, b, CompareConfig(pixel_threshold=1, changed_ratio_threshold=1.0))
        assert r.verdict is Verdict.CHANGED

    def test_ratio_threshold_boundary(self):
        a = make_png(BASE)
        b = fill_rect(a, 0, 0, 4, 4, (0, 0, 0))  # 16/256 = 0.0625
        r = compare_images(a, b, CompareConfig(changed_ratio_threshold=0.0625, pixel_threshold=10**9))
        assert r.verdict is Verdict.WITHIN_THRESHOLD
        r = compare_images(a, b, CompareConfig(changed_ratio_threshold=0.0624, pixel_threshold=10**9))
        assert r.verdict is Verdict.CHANGED

    def test_either_threshold_exceeded_means_changed(self):
        a = make_png(BASE)
        b = paint(a, {(1, 1): (0, 0, 0)})
        # 像素数阈值放宽但比例阈值收紧：任一超限即变化
        r = compare_images(a, b, CompareConfig(pixel_threshold=100, changed_ratio_threshold=0.0))
        assert r.verdict is Verdict.CHANGED


class TestIgnoreRegions:
    def test_change_inside_ignore_region_not_counted(self):
        a = make_png(BASE)
        b = fill_rect(a, 4, 4, 3, 3, (0, 0, 0))
        cfg = CompareConfig(ignore_regions=(Region(4, 4, 3, 3),))
        r = compare_images(a, b, cfg)
        assert r.verdict is Verdict.UNCHANGED
        assert r.changed_pixels == 0
        assert r.effective_pixels == 256 - 9

    def test_change_outside_ignore_region_counted(self):
        a = make_png(BASE)
        b = fill_rect(a, 0, 0, 8, 8, (0, 0, 0))
        cfg = CompareConfig(ignore_regions=(Region(0, 0, 8, 4),))
        r = compare_images(a, b, cfg)
        assert r.changed_pixels == 8 * 4

    def test_overlapping_regions_counted_once(self):
        a = make_png(BASE)
        cfg = CompareConfig(ignore_regions=(Region(0, 0, 4, 4), Region(2, 2, 4, 4)))
        r = compare_images(a, a, cfg)
        assert r.effective_pixels == 256 - (16 + 16 - 4)

    @pytest.mark.parametrize(
        "region, reason_part",
        [
            (Region(-1, 0, 4, 4), "negative"),
            (Region(0, 0, 0, 4), "positive"),
            (Region(14, 0, 4, 4), "exceeds"),
            (Region(0, 15, 4, 2), "exceeds"),
        ],
    )
    def test_invalid_region_rejected_with_location(self, region, reason_part):
        a = make_png(BASE)
        cfg = CompareConfig(ignore_regions=(Region(0, 0, 1, 1), region))
        with pytest.raises(IgnoreRegionError) as exc_info:
            compare_images(a, a, cfg)
        assert exc_info.value.region_index == 1  # 定位到具体区域
        assert reason_part in exc_info.value.reason


class TestTolerance:
    def test_scattered_noise_within_tolerance_ignored(self):
        a = make_png(BASE)
        noise = {(i, i): (BASE[0] + 2, BASE[1] - 2, BASE[2] + 1) for i in range(0, 16, 3)}
        b = paint(a, noise)
        r = compare_images(a, b, CompareConfig(tolerance=2))
        assert r.verdict is Verdict.UNCHANGED
        assert r.changed_pixels == 0

    def test_noise_above_tolerance_counted(self):
        a = make_png(BASE)
        b = paint(a, {(3, 3): (BASE[0] + 3, BASE[1], BASE[2])})
        r = compare_images(a, b, CompareConfig(tolerance=2))
        assert r.changed_pixels == 1

    def test_solid_color_block_not_swallowed(self):
        a = make_png(BASE)
        b = fill_rect(a, 0, 0, 8, 8, (BASE[0] + 2, BASE[1], BASE[2]))
        # 成片改变即使每像素差值小，也因数量超过阈值被判定
        r = compare_images(a, b, CompareConfig(tolerance=2, changed_ratio_threshold=0.01))
        assert r.verdict is Verdict.CHANGED

    def test_shift_not_swallowed(self):
        # 高对比图案整体平移 1px：边缘处差值远大于容忍度
        a = make_png((0, 0, 0), (20, 16))
        a = fill_rect(a, 8, 0, 8, 16, (255, 255, 255))
        b = make_png((0, 0, 0), (20, 16))
        b = fill_rect(b, 9, 0, 8, 16, (255, 255, 255))
        r = compare_images(a, b, CompareConfig(tolerance=10))
        assert r.verdict is Verdict.CHANGED
        assert r.changed_pixels == 2 * 16

    def test_deterministic_repeated_compare(self):
        a = make_png(BASE)
        b = paint(a, {(i, i): (0, 0, 0) for i in range(16)})
        cfg = CompareConfig(tolerance=1, ignore_regions=(Region(0, 0, 4, 4),))
        r1 = compare_images(a, b, cfg)
        r2 = compare_images(a, b, cfg)
        assert r1.diff_image == r2.diff_image  # 逐字节一致
        assert r1.verdict is r2.verdict
        assert r1.changed_pixels == r2.changed_pixels


class TestInputErrors:
    def test_corrupt_image(self):
        a = make_png(BASE)
        with pytest.raises(ImageDecodeError):
            compare_images(a, b"definitely not an image")

    def test_unsupported_format(self):
        a = make_png(BASE)
        with pytest.raises(ImageDecodeError):
            compare_images(a, b"GIF89a" + b"\x00" * 32)

    def test_dimension_mismatch(self):
        a = make_png(BASE, (16, 16))
        b = make_png(BASE, (8, 8))
        with pytest.raises(DimensionMismatchError):
            compare_images(a, b)

    def test_max_pixels_limit(self):
        a = make_png(BASE, (16, 16))
        cfg = CompareConfig(max_pixels=100)
        with pytest.raises(ResourceLimitError):
            compare_images(a, a, cfg)

    def test_max_dimension_limit(self):
        a = make_png(BASE, (16, 16))
        cfg = CompareConfig(max_width=8)
        with pytest.raises(ResourceLimitError):
            compare_images(a, a, cfg)

    def test_max_bytes_limit(self):
        a = make_png(BASE)
        cfg = CompareConfig(max_image_bytes=10)
        with pytest.raises(ResourceLimitError):
            compare_images(a, a, cfg)

    def test_error_types_are_distinguishable(self):
        a = make_png(BASE)
        with pytest.raises(ResourceLimitError) as e1:
            compare_images(a, a, CompareConfig(max_pixels=1))
        with pytest.raises(ImageDecodeError) as e2:
            compare_images(a, b"junk")
        assert not isinstance(e1.value, ImageDecodeError)
        assert not isinstance(e2.value, ResourceLimitError)
