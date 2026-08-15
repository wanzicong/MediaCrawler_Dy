"""Compatibility alias for :mod:`app.integrations.douyin.exceptions`."""

import sys

from app.integrations.douyin import exceptions as _implementation
from app.integrations.douyin.exceptions import (
    CDPConnectionError,
    DataFetchError,
    DouyinError,
    LoginError,
)

__all__ = ["CDPConnectionError", "DataFetchError", "DouyinError", "LoginError"]

# Keep both import paths bound to one module object. This is important for
# callers that monkeypatch an attribute through the historical import path.
sys.modules[__name__] = _implementation
