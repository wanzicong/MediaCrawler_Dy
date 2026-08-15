"""Compatibility alias for the canonical Douyin interaction adapter."""

import sys

from app.integrations.douyin import interactions as _implementation

sys.modules[__name__] = _implementation
