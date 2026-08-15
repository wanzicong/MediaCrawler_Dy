"""Compatibility alias for the canonical comment export application service."""

import sys

from app.application.douyin.comments import exports as _implementation

sys.modules[__name__] = _implementation
