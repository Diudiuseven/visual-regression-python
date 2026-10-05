"""Threshold boundaries, tolerance semantics and noise suppression."""
from __future__ import annotations

from visual_regression.config import CompareConfig, ResourceLimits
from visual_regression.diffing import compute_diff
from visual_regression.imaging import decode_image

from .conftest import image_png, solid, with_pixels

LIMITS = ResourceLimits()


def _diff(a_img, b_img, **cfg):
    a = decode_image(image_png(a_img), LIMITS)
    b = decode_image(image_png(b_img), LIMITS)
    return compute_diff(a, b, CompareConfig(**cfg), [])


def test_identical_images_report_no_diff():
    r = _diff(solid((10, 20, 30)), solid((10, 20, 30)))
    assert r.changed is False
    assert r.changed_pixels == 0
    assert r.ratio == 0.0


def test_channel_difference_at_or_below_tolerance_is_not_change():
    # |diff| exactly equals tolerance (16): condition is strict ">"
    r = _diff(solid((0, 0, 0), (10, 10)), solid((16, 16, 16), (10, 10)),
              pixel_tolerance=16, change_ratio=0.0)
    assert r.changed_pixels == 0 and r.changed is False


def test_channel_difference_one_above_tolerance_is_change():
    r = _diff(solid((0, 0, 0), (10, 10)), solid((17, 17, 17), (10, 10)),
              pixel_tolerance=16, change_ratio=0.0)
    assert r.changed_pixels == 100 and r.changed is True


def test_change_ratio_boundary_is_strict_greater():
    # 10x10 image: one changed pixel -> ratio exactly 0.01
    base = solid((0, 0, 0), (10, 10))
    cand = with_pixels((0, 0, 0), (10, 10), [((0, 0), (200, 200, 200))])
    at = _diff(base, cand, change_ratio=0.01)
    assert at.changed_pixels == 1 and at.ratio == 0.01 and at.changed is False
    below = _diff(base, cand, change_ratio=0.02)
    assert below.changed is False
    above = _diff(base, cand, change_ratio=0.005)
    assert above.changed is True


def test_two_pixels_cross_ratio():
    base = solid((0, 0, 0), (10, 10))
    cand = with_pixels((0, 0, 0), (10, 10), [
        ((0, 0), (200, 200, 200)), ((1, 0), (200, 200, 200)),
    ])
    r = _diff(base, cand, change_ratio=0.01)
    assert r.changed is True and r.changed_pixels == 2


def test_isolated_noise_cluster_filtered_but_patch_survives():
    base = solid((0, 0, 0), (12, 12))
    # two isolated pixels far apart + one 2x2 patch (4 connected pixels)
    cand = with_pixels((0, 0, 0), (12, 12), [
        ((0, 0), (255, 255, 255)),
        ((10, 11), (255, 255, 255)),
    ])
    for px in [(5, 5), (6, 5), (5, 6), (6, 6)]:
        cand.putpixel(px, (255, 255, 255))
    r = _diff(base, cand, change_ratio=0.0, min_cluster_size=3)
    # only the 2x2 patch survives
    assert r.changed_pixels == 4
    assert r.changed is True
    assert r.cluster_count == 1


def test_single_pixel_disappears_under_min_cluster_size():
    base = solid((0, 0, 0), (8, 8))
    cand = with_pixels((0, 0, 0), (8, 8), [((3, 3), (255, 0, 0))])
    r = _diff(base, cand, change_ratio=0.0, min_cluster_size=2)
    assert r.changed_pixels == 0 and r.changed is False
    assert r.cluster_count == 0


def test_structural_shift_is_not_swallowed_by_tolerance():
    # white 2x3 block shifted by one column creates a large connected diff
    base = solid((0, 0, 0), (20, 20))
    cand = solid((0, 0, 0), (20, 20))
    for x in range(2, 5):
        for y in range(2, 7):
            base.putpixel((x, y), (255, 255, 255))
    for x in range(3, 6):
        for y in range(2, 7):
            cand.putpixel((x, y), (255, 255, 255))
    # the shift leaves two 1-column strips of 5 pixels each: 10 changed
    # pixels, well above any reasonable noise filter.
    r = _diff(base, cand, pixel_tolerance=16, change_ratio=0.01, min_cluster_size=4)
    assert r.changed is True
    assert r.changed_pixels == 10


def test_repeated_runs_are_byte_identical():
    base = solid((10, 20, 30), (13, 7))
    cand = solid((10, 20, 30), (13, 7))
    cand.putpixel((4, 4), (9, 200, 12))
    a = decode_image(image_png(base), LIMITS)
    b = decode_image(image_png(cand), LIMITS)
    cfg = CompareConfig(pixel_tolerance=8, change_ratio=0.001)
    r1 = compute_diff(a, b, cfg, [])
    r2 = compute_diff(a, b, cfg, [])
    assert r1.diff_png == r2.diff_png
    assert r1.to_dict() == r2.to_dict()
