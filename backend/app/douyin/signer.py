"""Compatibility alias for :mod:`app.integrations.douyin.signer`."""

import sys

from app.integrations.douyin import signer as _implementation
from app.integrations.douyin.signer import get_a_bogus, get_web_id

__all__ = ["get_a_bogus", "get_web_id"]

sys.modules[__name__] = _implementation
