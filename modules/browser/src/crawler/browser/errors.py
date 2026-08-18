"""Errors raised by the CDP browser runtime."""


class CDPConnectionError(RuntimeError):
    """The CDP browser endpoint is unreachable or stopped responding."""
