"""抖音任务的请求风控档位：延迟档位 → 随机间隔区间。

档位语义属于 API 契约（``DouyinRequestDelayLevel`` 枚举），所以代码里保留一份
基线值；仓库根目录 ``config.yaml`` 的 ``risk_control.levels`` 可以覆盖**已存在
档位**的区间，便于按环境调松紧而不用改代码发版。枚举里没有的档位名不会生效
（请求侧根本选不中），这类拼写错误由架构测试在 CI 阶段拦截。
"""

from crawler.bootstrap.settings import settings

# 代码基线：与 config.yaml 出厂值一致，config.yaml 缺失时直接使用。
CODE_DEFAULT_PRESETS: dict[str, tuple[float, float]] = {
    "fast": (1.0, 2.0),
    "steady": (3.0, 6.0),
    "ultra_steady": (6.0, 12.0),
}


def delay_level_presets() -> dict[str, tuple[float, float]]:
    """返回延迟档位 → (下限, 上限) 映射；config.yaml 只覆盖它显式声明的档位。

    返回：
        以代码基线为底、被 config.yaml 覆盖后的区间映射。
    """
    presets = dict(CODE_DEFAULT_PRESETS)
    for level, config in settings.RISK_CONTROL_LEVELS.items():
        presets[level] = (config.interval_seconds[0], config.interval_seconds[1])
    return presets


def validate_task_size_limits(*, max_awemes: int, max_comments_per_aweme: int) -> None:
    """校验任务规模不超过服务端上限（上限由 config.yaml 的 risk_control.limits 决定）。

    模型层不再硬编码 1000 这类上限，避免「配置调大了但请求仍被字段约束拦住」。

    参数：
        max_awemes: 请求声明的单任务作品数上限。
        max_comments_per_aweme: 请求声明的单作品评论数上限。
    异常：
        ValueError: 任一数值超过配置上限时抛出（API 层映射为 422）。
    """
    if max_awemes > settings.DOUYIN_MAX_AWEMES_PER_TASK:
        raise ValueError(
            "max_awemes 超出服务端上限"
            f"（当前 {settings.DOUYIN_MAX_AWEMES_PER_TASK}，"
            "可在 config.yaml 的 risk_control.limits 调整）"
        )
    if max_comments_per_aweme > settings.DOUYIN_MAX_COMMENTS_PER_AWEME:
        raise ValueError(
            "max_comments_per_aweme 超出服务端上限"
            f"（当前 {settings.DOUYIN_MAX_COMMENTS_PER_AWEME}，"
            "可在 config.yaml 的 risk_control.limits 调整）"
        )


__all__ = [
    "CODE_DEFAULT_PRESETS",
    "delay_level_presets",
    "validate_task_size_limits",
]
