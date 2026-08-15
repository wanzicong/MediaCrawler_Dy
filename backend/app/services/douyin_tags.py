"""Compatibility alias for the canonical tag application service."""

import sys

from app.application.douyin.tags import service as _implementation

sys.modules[__name__] = _implementation
