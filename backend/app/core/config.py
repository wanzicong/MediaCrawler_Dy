"""Compatibility alias for the canonical application settings module."""

import sys

from app.bootstrap import settings as _implementation

sys.modules[__name__] = _implementation
