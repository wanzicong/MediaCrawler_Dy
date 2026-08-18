"""应用级日志安全防护配置。

防止第三方传输层客户端在日志中泄露带签名的 URL 与查询 token。
"""

import logging

# 可能输出敏感请求 URL 的传输层日志器名单
SENSITIVE_TRANSPORT_LOGGERS = ("httpx", "httpcore")


def configure_sensitive_transport_logging() -> None:
    """将传输层日志器级别提升为 WARNING，避免签名 URL 与查询 token 落入日志。"""
    for logger_name in SENSITIVE_TRANSPORT_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
