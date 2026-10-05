"""End-to-end determinism: identical requests yield byte-identical diffs."""
from __future__ import annotations

from visual_regression.config import CompareConfig

from .conftest import make_png


def test_repeated_compare_byte_identical_with_regions_and_noise_filter(service):
    base = make_png((30, 40, 50), (24, 24))
    service.compare_case("c", base)

    import io
    from PIL import Image

    cand_img = Image.new("RGB", (24, 24), (30, 40, 50))
    # isolated noise pixels + a sizable patch + changes inside ignored region
    cand_img.putpixel((1, 1), (250, 250, 250))
    cand_img.putpixel((22, 22), (250, 250, 250))
    for x in range(10, 16):
        for y in range(10, 16):
            cand_img.putpixel((x, y), (0, 200, 0))
    for x in range(0, 8):  # ignored strip
        cand_img.putpixel((x, 20), (255, 0, 0))
    buf = io.BytesIO()
    cand_img.save(buf, "PNG")
    candidate = buf.getvalue()

    cfg = CompareConfig(pixel_tolerance=8, change_ratio=0.01, min_cluster_size=3)
    regions = [{"x": 0, "y": 19, "width": 8, "height": 2}]

    results = [
        service.compare_case("c", candidate, config=cfg, ignore_regions=regions)
        for _ in range(5)
    ]
    arts = [service.get_artifact(r.artifact_id) for r in results]
    assert all(a == arts[0] for a in arts)
    assert results[0].status.value == "diff"
    # noise singles are dropped, patch survives, ignored strip excluded
    s = results[0].summary
    assert s["changed_pixels"] == 36
    assert s["ignored_pixels"] == 16
    assert s["cluster_count"] == 1


def test_same_request_across_independent_service_instances(service):
    from visual_regression.service import VisualRegressionService

    base = make_png((5, 6, 7), (10, 10))
    a = VisualRegressionService()
    b = VisualRegressionService()
    a.compare_case("c", base)
    b.compare_case("c", base)
    cand = make_png((9, 9, 9), (10, 10))
    ra = a.compare_case("c", cand, config=CompareConfig(pixel_tolerance=0))
    rb = b.compare_case("c", cand, config=CompareConfig(pixel_tolerance=0))
    assert a.get_artifact(ra.artifact_id) == b.get_artifact(rb.artifact_id)
    assert ra.summary == rb.summary


def test_annotation_colors_match_documented_legend(service):
    import io
    from PIL import Image

    from visual_regression.config import CompareConfig

    base = Image.new("RGB", (12, 12), (100, 100, 100))
    cand = Image.new("RGB", (12, 12), (100, 100, 100))
    cand.putpixel((0, 0), (255, 0, 0))                       # isolated noise
    for x in range(5, 9):                                    # surviving patch
        for y in range(5, 9):
            cand.putpixel((x, y), (0, 0, 255))

    def enc(im):
        buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

    service.compare_case("c", enc(base))
    item = service.compare_case(
        "c",
        enc(cand),
        config=CompareConfig(min_cluster_size=3, change_ratio=0.0),
        ignore_regions=[{"x": 10, "y": 10, "width": 2, "height": 2}],
    )
    out = Image.open(io.BytesIO(service.get_artifact(item.artifact_id))).convert("RGB")
    assert out.getpixel((0, 0)) == (210, 150, 0)     # amber: filtered noise
    assert out.getpixel((7, 7)) == (255, 0, 0)       # red: changed
    assert out.getpixel((2, 2)) == (40, 40, 40)      # dimmed unchanged
    assert out.getpixel((11, 11))[2] > out.getpixel((11, 11))[0]  # blue ignore fill
