"""Compatibility alias for the crawl application orchestrator."""

import sys

from app.application.douyin.tasks import crawler as _implementation

sys.modules[__name__] = _implementation
