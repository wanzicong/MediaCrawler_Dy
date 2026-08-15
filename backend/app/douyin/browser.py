"""Compatibility alias for the canonical Douyin CDP adapter."""

import sys

from app.integrations.douyin import browser as _implementation

sys.modules[__name__] = _implementation
