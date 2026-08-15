"""Compatibility alias for the canonical framework security module."""

import sys

from app.framework import security as _implementation

sys.modules[__name__] = _implementation
