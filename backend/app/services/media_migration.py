"""Compatibility alias for the canonical media migration application service."""

import sys

from app.application.douyin.media import migration as _implementation

sys.modules[__name__] = _implementation
