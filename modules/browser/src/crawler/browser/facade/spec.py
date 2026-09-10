"""浏览器会话连接参数：对外统一描述本地/远程 CDP 连接方式。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserSessionSpec:
    """描述一次 CDP 浏览器会话的连接方式（本地 profile 或远程 CDP）。

    该类型只承载连接参数，不持有任何站点语义；``browser_mode`` 取中立
    字符串 ``"local"`` / ``"remote"``，由调用方（如账号解析逻辑）负责
    把业务侧枚举桥接为字符串后传入。
    """

    browser_mode: str  # 浏览器模式：local（本地 profile）或 remote（远程 CDP）
    remote_host: str | None = None  # 远程 CDP 主机地址
    remote_port: int | None = None  # 远程 CDP 端口
    viewer_url: str | None = None  # 远程浏览器可视化查看地址（noVNC 等，非会话参数）
    user_data_dir: Path | None = None  # 本地浏览器用户数据目录
    debug_port: int | None = None  # 本地浏览器 CDP 调试端口
