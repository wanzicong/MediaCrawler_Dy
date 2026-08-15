"""Backward-compatible database bootstrap imports."""

from app.application.identity.bootstrap import init_db
from app.framework.database import engine

__all__ = ["engine", "init_db"]
