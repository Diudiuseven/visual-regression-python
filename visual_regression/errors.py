"""Error taxonomy for the visual regression pipeline."""
from __future__ import annotations


class VisualRegressionError(Exception):
    """Base class for all pipeline errors."""

    code: str = "visual_regression_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class InvalidInputError(VisualRegressionError):
    """Rejected input (bad parameters, corrupt images, oversize files)."""

    code = "invalid_input"


class UnsupportedFormatError(VisualRegressionError):
    """Image format is recognized but explicitly not supported."""

    code = "unsupported_format"


class ImageTooLargeError(VisualRegressionError):
    """Image exceeds the configured resource limits."""

    code = "image_too_large"


class DimensionMismatchError(VisualRegressionError):
    """Baseline and candidate do not share the same dimensions."""

    code = "dimension_mismatch"


class IgnoreRegionError(VisualRegressionError):
    """An ignore region is malformed or out of bounds."""

    code = "invalid_ignore_region"

    def __init__(self, message: str, *, index: int | None = None) -> None:
        super().__init__(message)
        self.index = index


class BaselineNotFoundError(VisualRegressionError):
    """Requested case / version does not exist."""

    code = "baseline_not_found"


class PendingChangeNotFoundError(VisualRegressionError):
    """No pending replacement exists for the case."""

    code = "pending_change_not_found"
