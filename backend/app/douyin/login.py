"""Compatibility alias for the canonical Douyin login adapter."""

import sys

from app.integrations.douyin import login as _implementation

sys.modules[__name__] = _implementation
