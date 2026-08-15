"""Compatibility alias for the canonical interaction application service."""

import sys

from app.application.douyin.interactions import service as _implementation

sys.modules[__name__] = _implementation
