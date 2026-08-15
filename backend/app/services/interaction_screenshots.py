"""Compatibility alias for the canonical interaction screenshot service."""

import sys

from app.application.douyin.interactions import screenshots as _implementation

sys.modules[__name__] = _implementation
