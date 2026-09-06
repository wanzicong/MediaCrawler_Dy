"""CDP 浏览器运行模式的枚举定义与兼容解析。

浏览器集成层持有自身中立的 ``DouyinBrowserMode`` 枚举：既为消费方提供稳定取值
语义，也避免对领域层（ORM 枚举）形成反向依赖。调用方传入的历史领域枚举会在
会话构造时通过 :func:`coerce_browser_mode` 归一化。
"""

from __future__ import annotations

from enum import Enum


class DouyinBrowserMode(str, Enum):
    """与 ORM 领域枚举保持独立的 CDP 浏览器模式枚举。

    历史浏览器模块曾作为导入副作用暴露 ``DouyinBrowserMode`` 符号。此处保留
    等价的中立枚举，既维持该导入路径可用，也保留枚举的 ``.value``/字符串行为，
    同时避免对领域层形成反向依赖。
    """

    local = "local"  # 本地模式：附加本机已开启 CDP 的浏览器，或由会话代为启动
    remote = (
        "remote"  # 远程模式：连接预先配置的远程 CDP 浏览器（如 Docker 容器中的 Chrome）
    )


def coerce_browser_mode(
    requested: str | object | None,
    default_value: str,
) -> tuple[object, DouyinBrowserMode]:
    """把调用方传入的模式归一化为内部取值，并保留可对外暴露的模式对象。

    参数：
        requested: 调用方显式传入的模式；可为字符串、领域枚举、本模块枚举或 None。
        default_value: requested 为 None 时使用的模式字符串取值。

    返回：
        (暴露给调用方的模式对象, 内部归一化的中立枚举)。
        显式传入的对象若带 ``.value``（如历史领域枚举）则原样保留为暴露对象，
        否则暴露归一化后的中立枚举。

    异常：
        ValueError: 模式取值无法解析为合法 DouyinBrowserMode 时抛出（文案与历史一致）。
    """
    candidate = requested if requested is not None else default_value
    mode_value = str(getattr(candidate, "value", candidate))
    try:
        canonical = DouyinBrowserMode(mode_value)
    except ValueError:
        # 保留历史领域枚举的校验报错文案，同时避免把该 ORM 枚举引入集成层。
        raise ValueError(f"{mode_value!r} is not a valid DouyinBrowserMode") from None
    exposed: object = candidate if hasattr(candidate, "value") else canonical
    return exposed, canonical
