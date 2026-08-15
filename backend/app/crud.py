"""Backward-compatible façade for the former mixed CRUD module.

Application code should import the identity or item use-case service directly.
"""

from app.application.identity.service import (
    DUMMY_HASH,
    authenticate,
    create_user,
    get_user_by_email,
    update_user,
)
from app.application.items.service import create_item

__all__ = [
    "DUMMY_HASH",
    "authenticate",
    "create_item",
    "create_user",
    "get_user_by_email",
    "update_user",
]
