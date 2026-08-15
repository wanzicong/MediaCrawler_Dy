"""Compatibility alias for the canonical remote CDP adapter."""

import sys

from app.integrations.douyin import remote_browser as _implementation

sys.modules[__name__] = _implementation
