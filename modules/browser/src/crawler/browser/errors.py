"""CDP 浏览器运行时抛出的异常类型定义。"""


class CDPConnectionError(RuntimeError):
    """CDP 浏览器端点不可达或停止响应时抛出的异常。"""
