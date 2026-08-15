"""Compatibility alias for the canonical crawl-task application service."""

import sys

from app.application.douyin.tasks import service as _implementation

sys.modules[__name__] = _implementation
