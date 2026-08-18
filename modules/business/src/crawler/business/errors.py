"""Errors raised by application services and translated by inbound adapters."""


class ResourceNotFoundError(Exception):
    """The requested business resource does not exist."""


class PermissionDeniedError(Exception):
    """The caller is not allowed to access the requested resource."""


class InvalidRequestError(Exception):
    """The submitted application request is invalid."""


class ConflictError(Exception):
    """The requested transition conflicts with current resource state."""


class ServiceUnavailableError(Exception):
    """A required application dependency is temporarily unavailable."""


class UnauthorizedError(Exception):
    """The request lacks a valid scoped application credential."""


__all__ = [
    "ConflictError",
    "InvalidRequestError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "ServiceUnavailableError",
    "UnauthorizedError",
]
