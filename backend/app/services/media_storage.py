"""Compatibility alias for the canonical media storage application service."""

import sys

from app.application.douyin.media import storage as _implementation

sys.modules[__name__] = _implementation
