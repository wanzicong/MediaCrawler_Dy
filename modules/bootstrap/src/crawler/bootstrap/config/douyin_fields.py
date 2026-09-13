"""账号登录会话、采集风控与互动风控字段。"""

from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self


class RiskControlLevelConfig(BaseModel):
    """单个请求延迟档位的随机间隔区间（秒）。"""

    interval_seconds: tuple[float, float]

    @model_validator(mode="after")
    def _validate_interval(self) -> Self:
        """校验区间形状：0 < 下限 ≤ 上限。"""
        lower, upper = self.interval_seconds
        if lower <= 0 or upper < lower:
            raise ValueError("interval_seconds 必须是 [下限, 上限]，且 0 < 下限 ≤ 上限")
        return self


class DouyinFields(BaseModel):
    """抖音账号会话、采集与互动的运行时策略。"""

    # 账号登录会话的有效期（秒），取值 60~3600，默认 900（15 分钟）
    DOUYIN_ACCOUNT_LOGIN_SESSION_TTL_SECONDS: int = Field(default=900, ge=60, le=3600)
    # 仅为向后兼容保留的环境配置项。账号失败仍会被记录并可将账号标记为不健康，
    # 但不再使账号进入基于时间的冷却状态。
    DOUYIN_ACCOUNT_FAILURE_COOLDOWN_SECONDS: int = Field(
        default=0, ge=0, le=86400
    )  # 账号失败冷却时长（秒），默认 0 表示不冷却

    DOUYIN_LOGIN_TIMEOUT: float = 600.0  # 扫码/账号登录流程的整体超时时间（秒）
    DOUYIN_REQUEST_TIMEOUT: float = 60.0  # 抖音接口单次请求超时时间（秒）
    DOUYIN_ACCOUNT_WAIT_POLL_SECONDS: float = Field(
        default=2.0, gt=0
    )  # 等待账号/账号池出现调度容量时的轮询间隔（秒）
    DOUYIN_REQUEST_SSL_VERIFY: bool = True  # 请求抖音接口时是否校验 SSL 证书

    DOUYIN_MAX_ACTIVE_TASKS: int = 1  # 同时运行的采集任务数上限
    DOUYIN_MAX_AWEMES_PER_TASK: int = 1000  # 单个任务最多采集的视频（aweme）数量
    DOUYIN_MAX_COMMENTS_PER_AWEME: int = 1000  # 单条视频最多采集的评论数量
    RISK_CONTROL_LEVELS: dict[str, RiskControlLevelConfig] = Field(
        default_factory=dict
    )  # 覆盖延迟档位的随机间隔区间（键为 fast / steady / ultra_steady 等档位名）

    DOUYIN_INTERACTION_DAILY_LIMIT: int = Field(
        default=50, ge=1, le=1000
    )  # 互动操作每日上限
    DOUYIN_INTERACTION_MIN_INTERVAL_SECONDS: float = Field(
        default=0.0, ge=0.0, le=3600.0
    )  # 两次互动操作之间的最小间隔（秒），0 表示不限制
    DOUYIN_INTERACTION_DUPLICATE_WINDOW_HOURS: int = Field(
        default=24, ge=1, le=720
    )  # 互动去重窗口（小时），窗口内对同一目标的重复操作将被拦截
    DOUYIN_INTERACTION_MAX_ATTEMPTS: int = Field(
        default=3, ge=1, le=10
    )  # 单次互动操作的最大重试次数
    DOUYIN_INTERACTION_SCREENSHOTS_ENABLED: bool = True  # 是否在互动过程中保存截图证据
    DOUYIN_INTERACTION_SCREENSHOT_DIR: Path = Path(
        "data/interaction-screenshots"
    )  # 互动截图保存目录（相对路径将拼接到仓库根目录）
    DOUYIN_INTERACTION_SCREENSHOT_QUALITY: int = Field(
        default=65, ge=30, le=90
    )  # 互动截图 JPEG 质量
    DOUYIN_INTERACTION_SCREENSHOT_TIMEOUT_SECONDS: float = Field(
        default=5.0, ge=1.0, le=15.0
    )  # 单次截图操作超时时间（秒）
    DOUYIN_INTERACTION_PAGE_READY_TIMEOUT_SECONDS: float = Field(
        default=45.0, ge=10.0, le=120.0
    )  # 等待互动目标页面就绪的超时时间（秒）
    DOUYIN_INTERACTION_NAVIGATION_ATTEMPTS: int = Field(
        default=3, ge=1, le=5
    )  # 页面导航失败时的最大尝试次数
    DOUYIN_INTERACTION_COMMENT_READY_TIMEOUT_SECONDS: float = Field(
        default=30.0, ge=5.0, le=90.0
    )  # 等待评论区就绪的超时时间（秒）
    DOUYIN_INTERACTION_EXECUTION_TIMEOUT_SECONDS: float = Field(
        default=300.0, ge=30.0, le=600.0
    )  # 单次互动执行的整体超时时间（秒）
