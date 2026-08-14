import logging

SENSITIVE_TRANSPORT_LOGGERS = ("httpx", "httpcore")


def configure_sensitive_transport_logging() -> None:
    """Prevent third-party clients from logging signed URLs and query tokens."""
    for logger_name in SENSITIVE_TRANSPORT_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
