"""Compatibility alias for the canonical framework logging module."""

import sys

from app.framework import logging as _implementation

sys.modules[__name__] = _implementation
