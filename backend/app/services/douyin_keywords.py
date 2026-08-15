"""Compatibility alias for the canonical keyword application service."""

import sys

from app.application.douyin.keywords import service as _implementation

sys.modules[__name__] = _implementation
