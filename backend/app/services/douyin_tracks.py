"""Compatibility alias for the canonical track application service."""

import sys

from app.application.douyin.tracks import service as _implementation

sys.modules[__name__] = _implementation
