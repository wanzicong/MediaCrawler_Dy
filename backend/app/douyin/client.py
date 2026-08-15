"""Compatibility alias for :mod:`app.integrations.douyin.client`."""

import sys

from app.integrations.douyin import client as _implementation
from app.integrations.douyin.client import (
    DouyinClient,
    browser_cookies,
    convert_cookies,
)

__all__ = ["DouyinClient", "browser_cookies", "convert_cookies"]

# Do not use a proxy module here: monkeypatching ``app.douyin.client`` must
# update globals used by the canonical client implementation as before.
sys.modules[__name__] = _implementation
