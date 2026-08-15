"""Compatibility alias for the canonical Douyin payload mapping adapter."""

import sys

from app.integrations.douyin import privacy as _implementation

sys.modules[__name__] = _implementation
