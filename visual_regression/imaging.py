"""Image decoding, normalization and diff-image encoding (in-process).

Only PNG and JPEG payloads are accepted (format is identified by Pillow's
sniffing, not by the file name). Decoded images are flattened to packed RGB,
so every downstream comparison works on a canonical byte representation.
"""
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from .config import ResourceLimits
from .errors import (
    ImageTooLargeError,
    InvalidInputError,
    UnsupportedFormatError,
)

SUPPORTED_FORMATS = frozenset({"PNG", "JPEG"})


class DecodedImage:
    """An RGB image held as a packed bytes buffer plus dimensions."""

    __slots__ = ("rgb", "width", "height")

    def __init__(self, rgb: bytes, width: int, height: int) -> None:
        if len(rgb) != width * height * 3:
            raise InvalidInputError("rgb buffer length does not match dimensions")
        self.rgb = rgb
        self.width = width
        self.height = height

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


def decode_image(data: bytes, limits: ResourceLimits) -> DecodedImage:
    """Decode *data* into a normalized RGB DecodedImage, enforcing limits.

    Raises:
        InvalidInputError: empty/truncated/corrupt payload.
        UnsupportedFormatError: recognized but unsupported image format.
        ImageTooLargeError: encoded size or decoded dimensions exceed limits.
    """
    limits.validate()
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise InvalidInputError("image payload is empty")
    if len(data) > limits.max_bytes:
        raise ImageTooLargeError(
            f"encoded image is {len(data)} bytes, limit is {limits.max_bytes}"
        )

    try:
        im = Image.open(io.BytesIO(bytes(data)))
        fmt = (im.format or "").upper()
        im.load()
    except UnidentifiedImageError as exc:
        raise InvalidInputError("unable to identify image data (corrupt or not an image)") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        # EOFError for truncated PNGs is an OSError subclass.
        raise InvalidInputError(f"corrupt or truncated image: {exc}") from exc

    if fmt not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"image format {fmt or 'unknown'} is not supported; allowed: PNG, JPEG"
        )

    width, height = im.size
    if width <= 0 or height <= 0:
        raise InvalidInputError("image has non-positive dimensions")
    if width > limits.max_width or height > limits.max_height:
        raise ImageTooLargeError(
            f"image dimensions {width}x{height} exceed "
            f"{limits.max_width}x{limits.max_height}"
        )
    if width * height > limits.max_pixels:
        raise ImageTooLargeError(
            f"image has {width * height} pixels, limit is {limits.max_pixels}"
        )

    rgb = _flatten_to_rgb(im)
    return DecodedImage(rgb, width, height)


def _flatten_to_rgb(im: Image.Image) -> bytes:
    """Return packed RGB bytes, compositing alpha over black when present."""
    mode = im.mode
    if mode == "RGB":
        return im.tobytes()
    if mode in ("RGBA", "LA", "PA", "La") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (0, 0, 0))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg.tobytes()
    if mode == "L":
        return im.convert("RGB").tobytes()
    if mode == "P":
        rgba = im.convert("RGBA")
        if "transparency" in im.info:
            bg = Image.new("RGB", rgba.size, (0, 0, 0))
            bg.paste(rgba, mask=rgba.split()[-1])
            return bg.tobytes()
        return rgba.convert("RGB").tobytes()
    return im.convert("RGB").tobytes()


def encode_diff_png(rgb: bytes, width: int, height: int) -> bytes:
    """Deterministically encode an RGB buffer as a PNG byte string.

    No timestamps or other metadata are written, and compression settings
    are fixed, so identical pixel buffers yield byte-identical output.
    """
    im = Image.frombytes("RGB", (width, height), bytes(rgb))
    buf = io.BytesIO()
    im.save(
        buf,
        format="PNG",
        compress_level=6,
        optimize=False,
    )
    return buf.getvalue()
