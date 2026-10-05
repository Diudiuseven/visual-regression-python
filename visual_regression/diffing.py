"""Core pixel comparison, noise suppression and annotation rendering.

Semantics (see docs/configuration.md for the full description):

* A pixel is *raw-changed* when at least one RGB channel satisfies
  ``|a - b| > pixel_tolerance``. Pixels at or below the tolerance never
  count, so sparse sub-tolerance rendering jitter is ignored.
* Raw-changed pixels are grouped into 4-connected components (runs merged
  by union-find). Components smaller than ``min_cluster_size`` are isolated
  noise and discarded. A coordinate shift or a recolored patch forms one
  large component and therefore survives this filter.
* The verdict is CHANGED iff the surviving changed pixels make up a
  fraction of the non-ignored area strictly greater than ``change_ratio``.
* The annotated PNG is produced with integer arithmetic in fixed Pillow
  operations, so it is byte-identical for repeated identical runs.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from .config import CompareConfig
from .imaging import DecodedImage, encode_diff_png
from .regions import Region, build_ignore_mask


@dataclass(frozen=True)
class DiffResult:
    changed: bool
    changed_pixels: int
    ratio: float
    considered_pixels: int
    ignored_pixels: int
    cluster_count: int
    diff_png: bytes

    def to_dict(self) -> dict:
        return {
            "changed": self.changed,
            "changed_pixels": self.changed_pixels,
            "ratio": self.ratio,
            "considered_pixels": self.considered_pixels,
            "ignored_pixels": self.ignored_pixels,
            "cluster_count": self.cluster_count,
        }


def _mark_raw_changes(
    base_img: Image.Image,
    cand_img: Image.Image,
    width: int,
    height: int,
    ignored: bytearray,
    tol: int,
) -> bytearray:
    """Return a per-pixel mask where a channel delta is strictly above tol."""
    diff = ImageChops.difference(base_img, cand_img)
    lut = bytes([0] * (tol + 1)) + bytes([1] * (255 - tol))
    r, g, b = diff.split()
    # point(lut) yields 0/1 per channel; lighter() is a per-pixel maximum,
    # so OR the three channels entirely in C.
    hit = ImageChops.lighter(r.point(lut), ImageChops.lighter(g.point(lut), b.point(lut)))
    mask = bytearray(hit.tobytes())
    if ignored:
        for i in range(len(mask)):
            if ignored[i]:
                mask[i] = 0
    return mask


def _runs_of_row(raw: bytes, base: int, width: int) -> list[tuple[int, int]]:
    """Find 1-runs in a row slice using C-level bytes searches."""
    row = raw[base : base + width]
    runs: list[tuple[int, int]] = []
    pos = 0
    while True:
        x0 = row.find(b"\x01", pos)
        if x0 == -1:
            return runs
        x1 = row.find(b"\x00", x0 + 1)
        if x1 == -1:
            runs.append((x0, width))
            return runs
        runs.append((x0, x1))
        pos = x1 + 1


def _resolve(parent: list[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: list[int], x: int, y: int) -> None:
    rx, ry = _resolve(parent, x), _resolve(parent, y)
    if rx != ry:
        if rx < ry:
            parent[ry] = rx
        else:
            parent[rx] = ry


def _label_runs(
    raw: bytes, width: int, height: int
) -> tuple[list[list[tuple[int, int, int]]], list[int]]:
    parent: list[int] = []
    rows: list[list[tuple[int, int, int]]] = []
    prev: list[tuple[int, int, int]] = []
    for row in range(height):
        current: list[tuple[int, int, int]] = []
        for x0, x1 in _runs_of_row(raw, row * width, width):
            label = len(parent)
            parent.append(label)
            for px0, px1, plabel in prev:
                if px0 >= x1:
                    break
                if px1 > x0:
                    _union(parent, label, plabel)
            current.append((x0, x1, label))
        rows.append(current)
        prev = current
    for i in range(len(parent)):
        parent[i] = _resolve(parent, i)
    return rows, parent


def compute_diff(
    baseline: DecodedImage,
    candidate: DecodedImage,
    config: CompareConfig,
    regions: list[Region],
) -> DiffResult:
    """Compare two equal-size images and render an annotated diff PNG."""
    config.validate()
    if baseline.size != candidate.size:
        from .errors import DimensionMismatchError

        raise DimensionMismatchError(
            f"baseline {baseline.size} and candidate {candidate.size} must match"
        )

    width, height = baseline.width, baseline.height
    total = width * height
    ignore_mask = build_ignore_mask(regions, width, height)
    ignored_pixels = sum(ignore_mask)
    considered = total - ignored_pixels

    base_img = Image.frombytes("RGB", (width, height), baseline.rgb)
    cand_img = Image.frombytes("RGB", (width, height), candidate.rgb)
    raw = _mark_raw_changes(
        base_img, cand_img, width, height, ignore_mask, config.pixel_tolerance
    )
    rows, parent = _label_runs(raw, width, height)

    comp_sizes: dict[int, int] = {}
    for current in rows:
        for x0, x1, label in current:
            root = parent[label]
            comp_sizes[root] = comp_sizes.get(root, 0) + (x1 - x0)

    surviving = {root for root, size in comp_sizes.items() if size >= config.min_cluster_size}
    changed_pixels = sum(size for root, size in comp_sizes.items() if root in surviving)
    ratio = (changed_pixels / considered) if considered else 0.0
    changed = considered > 0 and changed_pixels > config.change_ratio * considered

    # build surviving/noise masks by painting runs (run count, not pixels,
    # drives Python work)
    surviving_mask = bytearray(total)
    noise_mask = bytearray(total)
    for row, current in enumerate(rows):
        base = row * width
        for x0, x1, label in current:
            target = surviving_mask if parent[label] in surviving else noise_mask
            target[base + x0 : base + x1] = b"\x01" * (x1 - x0)

    diff_png = _render(
        cand_img, ignore_mask, surviving_mask, noise_mask, regions, width, height
    )
    return DiffResult(
        changed=changed,
        changed_pixels=changed_pixels,
        ratio=ratio,
        considered_pixels=considered,
        ignored_pixels=ignored_pixels,
        cluster_count=len(surviving),
        diff_png=diff_png,
    )


def _mask_image(mask: bytearray, width: int, height: int) -> Image.Image:
    """Build an L alpha mask: flag 1 becomes fully opaque (255)."""
    l = Image.frombytes("L", (width, height), bytes(mask))
    return l.point(bytes([0]) + bytes([255]) * 255)


def _render(
    candidate: Image.Image,
    ignored: bytearray,
    changed_mask: bytearray,
    noise_mask: bytearray,
    regions: list[Region],
    width: int,
    height: int,
) -> bytes:
    # dim unchanged candidate pixels (0.4x), deterministic integer math
    out = Image.eval(candidate, lambda v: v * 4 // 10).convert("RGB")

    if any(noise_mask):
        out.paste(Image.new("RGB", (width, height), (210, 150, 0)),
                  (0, 0), _mask_image(noise_mask, width, height))
    if any(changed_mask):
        out.paste(Image.new("RGB", (width, height), (255, 0, 0)),
                  (0, 0), _mask_image(changed_mask, width, height))

    if ignored:
        cand_dim = Image.eval(candidate, lambda v: v * 2 // 10).convert("RGB")
        fill = ImageChops.add(cand_dim, Image.new("RGB", (width, height), (10, 10, 70)))
        out.paste(fill, (0, 0), _mask_image(ignored, width, height))
        draw = ImageDraw.Draw(out)
        for region in regions:
            draw.rectangle(
                (region.x, region.y, region.x + region.width - 1,
                 region.y + region.height - 1),
                outline=(100, 170, 255),
            )

    return encode_diff_png(out.tobytes(), width, height)
