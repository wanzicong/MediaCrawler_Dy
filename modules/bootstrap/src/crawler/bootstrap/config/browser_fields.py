"""浏览器模式、本机/远程槽位与 config.yaml 的槽位声明模型。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .base import BASE_DIR


class BrowserSlotLocalConfig(BaseModel):
    """config.yaml 中声明的本机浏览器槽位。"""

    name: str = Field(min_length=1, max_length=64)  # 槽位名（账号绑定取值，如 local-1）
    label: str | None = Field(
        default=None, max_length=100
    )  # 展示名；缺省按「本机浏览器 N」推导
    port: int = Field(ge=1024, le=65535)  # 该槽位的 CDP 调试端口
    profile_dir: Path | None = None  # 用户数据目录；缺省落在本机槽位根目录下
    enabled: bool = True  # 为 False 时不参与槽位列表与账号绑定

    @field_validator("profile_dir")
    @classmethod
    def _resolve_profile_dir(cls, value: Path | None) -> Path | None:
        """把相对 Profile 目录解析到仓库根目录下（与 .env 的相对路径规则一致）。"""
        if value is None or value.is_absolute():
            return value
        return BASE_DIR / value


class BrowserSlotRemoteConfig(BaseModel):
    """config.yaml 中声明的远程（容器）浏览器槽位。"""

    name: str = Field(min_length=1, max_length=64)  # 槽位名（账号绑定取值）
    label: str | None = Field(default=None, max_length=100)  # 展示名；缺省用槽位名
    host: str = Field(min_length=1, max_length=255)  # CDP 主机名或 IP
    port: int = Field(ge=1, le=65535)  # CDP 端口
    viewer_url: str | None = None  # noVNC 等可视化查看地址
    enabled: bool = True  # 为 False 时不参与槽位列表与账号绑定


class BrowserSlotsConfig(BaseModel):
    """浏览器槽位配置：显式声明优先，留空则回落到环境变量派生规则。"""

    local: list[BrowserSlotLocalConfig] = Field(default_factory=list)
    remote: list[BrowserSlotRemoteConfig] = Field(default_factory=list)


class BrowserFields(BaseModel):
    """浏览器运行时配置。

    抖音采集器的浏览器自动化只使用 CDP：应用绝不回退到 chromium.launch() 或
    launch_persistent_context()。
    """

    DOUYIN_BROWSER_MODE: Literal["local", "remote"] = (
        "remote"  # 浏览器模式：remote 远程 CDP，local 本机浏览器
    )
    DOUYIN_CDP_HOST: str = "127.0.0.1"  # CDP 调试主机地址；本地模式下必须是本机地址
    DOUYIN_CDP_PORT: int = 9222  # CDP 调试端口
    DOUYIN_CDP_CONNECT_EXISTING: bool = (
        False  # 为 True 时附加到已开启 CDP 的既有浏览器，不再代为启动
    )
    DOUYIN_CDP_CONNECT_TIMEOUT: float = 60.0  # 等待 CDP 浏览器就绪/连接的超时时间（秒）
    DOUYIN_CDP_BROWSER_PATH: str = (
        ""  # 浏览器可执行文件路径；为空时自动探测本机 Chrome/Edge
    )
    DOUYIN_CDP_USER_DATA_DIR: Path = Path(
        "browser_data/douyin"
    )  # 本地浏览器用户数据目录（相对路径将拼接到仓库根目录）
    DOUYIN_CDP_HEADLESS: bool = False  # 本地启动浏览器时是否使用无头模式
    DOUYIN_CDP_AUTO_CLOSE: bool = True  # 会话结束时是否自动关闭由会话托管的浏览器进程

    # 本机浏览器槽位：本机可同时托管多个独立 Profile 的 Chrome/Edge，
    # 每个槽位独占绑定一个账号（与远程槽位同一套槽位/绑定语义）。
    # 槽位名为 local-1 … local-N，端口自 DOUYIN_LOCAL_CDP_PORT_BASE 起递增，
    # Profile 落在 DOUYIN_LOCAL_CDP_USER_DATA_DIR/<槽位名> 下。
    DOUYIN_LOCAL_CDP_SLOT_COUNT: int = Field(
        default=4, ge=0, le=32
    )  # 本机浏览器槽位数量，默认 4 个；0 表示不启用本机槽位
    DOUYIN_LOCAL_CDP_PORT_BASE: int = Field(
        default=9333, ge=1024, le=65000
    )  # 本机槽位 CDP 调试端口起始值（第 n 个槽位为 base + n - 1）
    DOUYIN_LOCAL_CDP_USER_DATA_DIR: Path = Path(
        "browser_data/douyin-local"
    )  # 本机槽位 Profile 根目录（相对路径将拼接到仓库根目录）

    # 原生（非容器）后端默认走浏览器容器映射到本机回环地址的端口；
    # compose.yml 会用 Docker DNS 端点覆盖这两项配置。
    DOUYIN_REMOTE_CDP_HOST: str = "127.0.0.1"  # 远程 CDP 浏览器主机名或 IP
    DOUYIN_REMOTE_CDP_PORT: int = 9223  # 远程 CDP 浏览器端口
    # 可选的命名浏览器槽位 JSON 对象。示例：
    # {"account-1":{"host":"127.0.0.1","port":9223,"viewer_url":"http://127.0.0.1:6081/vnc.html?autoconnect=1"}}
    DOUYIN_REMOTE_CDP_SLOTS: str = (
        ""  # 命名浏览器槽位配置（JSON 字符串），空串表示不启用多槽位
    )
    DOUYIN_REMOTE_VIEWER_URL: str = "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale"  # 远程浏览器 noVNC 查看器地址，用于前端展示实时画面

    # config.yaml 承载的结构化槽位声明（YAML 排在环境变量与 .env 之后）
    BROWSER_SLOTS: BrowserSlotsConfig = (
        BrowserSlotsConfig()
    )  # 显式声明的本机/远程槽位；留空回落到上面的派生规则
