"""Compatibility alias for the canonical media preview application service."""

import sys

from app.application.douyin.media import preview as _implementation

sys.modules[__name__] = _implementation
