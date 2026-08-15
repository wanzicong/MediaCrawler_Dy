"""Compatibility alias for the canonical account application service."""

import sys

from app.application.douyin.accounts import service as _implementation

sys.modules[__name__] = _implementation
