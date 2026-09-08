# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""互动执行的数据模型：请求/结果/连接参数与旧版账号访问协议。

纯数据结构与结构化协议集中于此；页面操作实现见同目录的
``response_inspector`` / ``page_controller`` / ``comment_locator`` / ``submit_flow``，
编排与 CDP 连接解析见 ``executor``。互动执行异常定义在 ``base.errors``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from playwright.async_api import Page

# 互动步骤回调：参数为当前页面、步骤标识与步骤说明
InteractionStepCallback = Callable[[Page, str, str], Awaitable[None]]


class _LegacyAccountId(Protocol):
    """旧版账号 ID 的结构化协议（仅要求 int 属性）。"""

    int: int  # 账号整数 ID


class _LegacyInteractionAccount(Protocol):
    """旧版互动账号对象的结构化协议，仅声明本模块需要的属性。"""

    id: _LegacyAccountId  # 账号 ID
    browser_mode: object  # 浏览器模式（枚举或其原始值）
    profile_key: str  # 本地 profile 目录名
    remote_slot: str | None  # 远程浏览器槽位名，None 表示使用默认远程配置


@dataclass(frozen=True)
class InteractionExecutionRequest:
    """互动执行请求参数。

    属性：
        interaction_type: 互动类型：video_comment（评论作品）/ comment_reply（回复评论）/ 其他为私信作者。
        aweme_id: 目标作品 ID。
        content: 互动文本内容。
        target_comment_id: 目标评论 ID（comment_reply 时使用）。
        target_comment_content: 目标评论内容，用于页面内定位。
        target_parent_comment_id: 目标评论的父评论 ID（回复二级评论时使用）。
    """

    interaction_type: str  # 互动类型：video_comment / comment_reply / 私信作者
    aweme_id: str  # 目标作品 ID
    content: str  # 互动文本内容
    target_comment_id: str | None = None  # 目标评论 ID
    target_comment_content: str | None = None  # 目标评论内容，用于页面内定位
    target_parent_comment_id: str | None = None  # 目标评论的父评论 ID


@dataclass(frozen=True)
class InteractionExecutionResult:
    """互动执行结果。

    属性：
        platform_id: 平台侧返回的评论 ID 等标识，未能解析时为 None。
    """

    platform_id: str | None = None  # 平台侧返回的评论 ID 等标识


@dataclass(frozen=True)
class InteractionBrowserConnection:
    """由应用层解析好的 CDP 连接参数（纯基础设施数据）。"""

    browser_mode: str  # 浏览器模式：local（本地 profile）或 remote（远程 CDP）
    remote_host: str | None = None  # 远程 CDP 主机
    remote_port: int | None = None  # 远程 CDP 端口
    user_data_dir: Path | None = None  # 本地浏览器用户数据目录
    debug_port: int | None = None  # 本地浏览器 CDP 调试端口
