"""Compatibility alias for the crawl persistence application service."""

import sys

from app.application.douyin.tasks import persistence as _implementation

sys.modules[__name__] = _implementation
