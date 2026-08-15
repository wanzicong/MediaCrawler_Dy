"""Compatibility alias for the canonical media pipeline application service."""

import sys

from app.application.douyin.media import pipeline as _implementation

sys.modules[__name__] = _implementation
