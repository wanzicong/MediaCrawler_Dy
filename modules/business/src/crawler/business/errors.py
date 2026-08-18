"""应用服务层抛出的业务错误类型，由入口适配层（如 HTTP 路由）翻译为对外响应。"""


class ResourceNotFoundError(Exception):
    """请求的业务资源不存在。"""


class PermissionDeniedError(Exception):
    """调用方无权访问请求的资源。"""


class InvalidRequestError(Exception):
    """提交的应用请求不合法。"""


class ConflictError(Exception):
    """请求的状态变更与资源当前状态冲突。"""


class ServiceUnavailableError(Exception):
    """必需的应用依赖暂时不可用。"""


class UnauthorizedError(Exception):
    """请求缺少有效的、具备相应作用域的应用凭证。"""


__all__ = [
    "ConflictError",
    "InvalidRequestError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "ServiceUnavailableError",
    "UnauthorizedError",
]
