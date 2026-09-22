"""抖音账号限界上下文的业务模型与 schema：账号、账号池、浏览器槽位及登录会话。"""

import uuid
from datetime import date, datetime
from enum import Enum

from crawler.business.common.models import get_datetime_utc
from sqlalchemy import DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class DouyinBrowserMode(str, Enum):
    """账号关联浏览器的运行模式。"""

    local = "local"  # 本地模式：使用服务本机的 CDP 浏览器与独立用户数据目录
    remote = "remote"  # 远程模式：连接 Docker 容器中的远程 CDP 浏览器槽位


class DouyinAccountStatus(str, Enum):
    """抖音账号生命周期状态，调度器据此判断账号是否可被选中执行任务。"""

    login_required = "login_required"  # 待登录：尚未完成登录身份验证
    verifying = "verifying"  # 验证中：正在进行登录/身份验证流程
    ready = "ready"  # 就绪：已登录且可调度
    busy = "busy"  # 执行中：存在正在执行的任务租约
    cooldown = "cooldown"  # 冷却中：触发风控/限流后暂时挂起，可被调度时自动恢复
    unhealthy = "unhealthy"  # 异常：连续失败或浏览器不可用，暂停调度
    disabled = "disabled"  # 已停用：用户手动停用，不参与调度


class DouyinAccountPoolStrategy(str, Enum):
    """账号池的账号调度策略。"""

    least_loaded = "least_loaded"  # 最少负载优先：优先选择租约占用率最低的账号
    round_robin = "round_robin"  # 轮询：依赖池上的 rotation_cursor 游标依次轮转
    weighted_round_robin = "weighted_round_robin"  # 加权轮询：按 weight 权重分摊负载


class DouyinAccountCreate(SQLModel):
    """创建抖音账号的请求模型。"""

    name: str = Field(min_length=1, max_length=80)  # 账号名称（同一用户内唯一）
    browser_mode: DouyinBrowserMode = (
        DouyinBrowserMode.remote
    )  # 浏览器运行模式，默认远程
    slot: str | None = Field(
        default=None, max_length=64
    )  # 绑定的浏览器槽位名，按 browser_mode 解析；远程为空表示默认槽位
    weight: int = Field(
        default=1, ge=1, le=100
    )  # 调度权重（1~100），加权轮询策略下生效
    priority: int = Field(
        default=0, ge=-100, le=100
    )  # 调度优先级（-100~100），数值越大越优先
    concurrency_limit: int = Field(default=1, ge=1, le=3)  # 单账号最大并发任务数（1~3）
    daily_task_limit: int = Field(default=100, ge=1, le=10000)  # 每日任务数上限
    min_request_interval_seconds: float = Field(
        default=1.0, ge=0.2, le=60.0
    )  # 该账号两次请求的最小间隔（秒）


class DouyinAccountUpdate(SQLModel):
    """更新抖音账号的请求模型，所有字段可选，仅更新显式传入的字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=80)  # 账号名称
    slot: str | None = Field(default=None, max_length=64)  # 浏览器槽位名
    weight: int | None = Field(default=None, ge=1, le=100)  # 调度权重
    priority: int | None = Field(default=None, ge=-100, le=100)  # 调度优先级
    concurrency_limit: int | None = Field(
        default=None, ge=1, le=3
    )  # 单账号最大并发任务数
    daily_task_limit: int | None = Field(default=None, ge=1, le=10000)  # 每日任务数上限
    min_request_interval_seconds: float | None = Field(
        default=None, ge=0.2, le=60.0
    )  # 请求最小间隔（秒）
    enabled: bool | None = None  # 是否启用；停用时状态联动为 disabled


class DouyinAccount(SQLModel, table=True):
    """抖音账号实体：一个可登录、可调度的抖音身份及其浏览器绑定与运行状态。

    不持久化 cookie 明文，仅以 identity_hash 记录登录身份；登录态由
    对应浏览器 Profile 的用户数据目录承载。
    """

    __tablename__ = "douyin_account"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_douyin_account_owner_name"),
        UniqueConstraint(
            "owner_id", "profile_key", name="uq_douyin_account_owner_profile"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 账号记录主键
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 id（外键 user.id，级联删除）
    name: str = Field(max_length=80, index=True)  # 账号名称（同一用户内唯一）
    browser_mode: str = Field(
        default=DouyinBrowserMode.remote.value, max_length=16, index=True
    )  # 浏览器运行模式（local/remote）
    profile_key: str = Field(
        max_length=64
    )  # 浏览器 Profile 目录键，本地模式下作为用户数据目录名
    slot: str | None = Field(
        default=None, max_length=64, index=True
    )  # 绑定的浏览器槽位名（本机如 local-1、远程为命名槽位）；远程为空表示
    # Docker 默认槽位，本机为空表示沿用账号独立 Profile（历史账号兼容）
    status: str = Field(
        default=DouyinAccountStatus.login_required.value,
        max_length=32,
        index=True,
    )  # 账号当前状态（见 DouyinAccountStatus）
    identity_hash: str = Field(
        default="", max_length=64
    )  # 登录身份哈希（脱敏后的 uid/sec_uid）；非空即视为已登录
    weight: int = Field(default=1, ge=1, le=100)  # 调度权重
    priority: int = Field(default=0, ge=-100, le=100)  # 调度优先级
    concurrency_limit: int = Field(default=1, ge=1, le=3)  # 单账号最大并发任务数
    daily_task_limit: int = Field(default=100, ge=1, le=10000)  # 每日任务数上限
    tasks_today: int = Field(
        default=0, ge=0
    )  # 今日已承接任务数（配合 usage_date 跨天重置）
    usage_date: date = Field(default_factory=date.today)  # tasks_today 统计对应的日期
    min_request_interval_seconds: float = Field(default=1.0)  # 两次请求的最小间隔（秒）
    active_leases: int = Field(default=0, ge=0)  # 当前执行中的任务租约数
    failure_streak: int = Field(
        default=0, ge=0
    )  # 连续任务失败次数（达到阈值置为 unhealthy）
    cooldown_until: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 冷却截止时间；None 表示未在冷却中
    last_verified_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次登录身份验证成功时间
    last_used_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近一次被调度执行时间
    last_error: str | None = Field(default=None, sa_type=Text)  # 最近一次错误信息
    enabled: bool = Field(default=True, index=True)  # 是否启用
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间（UTC）
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近更新时间（UTC）


class DouyinAccountPublic(SQLModel):
    """账号对外响应模型（不包含 identity_hash、profile_key 等内部字段）。"""

    id: uuid.UUID  # 账号 id
    name: str  # 账号名称
    browser_mode: DouyinBrowserMode  # 浏览器运行模式
    slot: str | None  # 绑定的浏览器槽位名
    status: DouyinAccountStatus  # 账号当前状态
    is_logged_in: bool  # 是否已登录（由 identity_hash 是否非空推导）
    weight: int  # 调度权重
    priority: int  # 调度优先级
    concurrency_limit: int  # 单账号最大并发任务数
    daily_task_limit: int  # 每日任务数上限
    tasks_today: int  # 今日已承接任务数
    min_request_interval_seconds: float  # 请求最小间隔（秒）
    active_leases: int  # 当前执行中的任务租约数
    failure_streak: int  # 连续失败次数
    cooldown_until: datetime | None  # 冷却截止时间
    last_verified_at: datetime | None  # 最近一次登录验证成功时间
    last_used_at: datetime | None  # 最近一次被调度执行时间
    last_error: str | None  # 最近一次错误信息
    enabled: bool  # 是否启用
    created_at: datetime  # 创建时间
    updated_at: datetime  # 最近更新时间


class DouyinAccountsPublic(SQLModel):
    """账号分页列表响应。"""

    data: list[DouyinAccountPublic]  # 当前页账号列表
    count: int  # 满足条件的账号总数


class DouyinBrowserSlotPublic(SQLModel):
    """浏览器槽位（本机或远程）的占用与健康状态，供槽位管理页展示。"""

    browser_mode: DouyinBrowserMode  # 槽位所属运行模式：local 本机 / remote 远程
    name: str | None  # 槽位名；None 表示 Docker 默认槽位
    label: str  # 槽位展示名称
    is_default: bool  # 是否为默认槽位
    available: bool  # 是否可用（已配置且未被账号绑定）
    configured: bool  # host/port 是否已正确配置
    cdp_endpoint: str | None  # CDP 调试端点（host:port）；未配置时为 None
    viewer_available: bool  # 是否配置了可视化查看地址
    viewer_url: str | None  # 可视化查看地址（noVNC 等）；本机槽位为本机浏览器窗口
    cdp_healthy: bool  # CDP 接口健康探测是否通过
    page_count: int  # 浏览器当前打开的页面数
    active_page_title: str | None  # 活动页面标题
    active_page_url: str | None  # 活动页面 URL（已剥离 query 参数）
    latency_ms: int | None  # 健康探测耗时（毫秒）
    checked_at: datetime  # 本次探测时间
    occupied_account_id: uuid.UUID | None  # 绑定该槽位的账号 id
    occupied_account_name: str | None  # 绑定该槽位的账号名称


class DouyinBrowserSlotsPublic(SQLModel):
    """浏览器槽位列表响应（本机槽位在前，远程槽位在后）。"""

    data: list[DouyinBrowserSlotPublic]  # 槽位状态列表
    count: int  # 槽位总数


class DouyinAccountPoolCreate(SQLModel):
    """创建账号池的请求模型。"""

    name: str = Field(min_length=1, max_length=80)  # 账号池名称（同一用户内唯一）
    description: str = Field(default="", max_length=500)  # 账号池描述
    strategy: DouyinAccountPoolStrategy = (
        DouyinAccountPoolStrategy.least_loaded
    )  # 调度策略，默认最少负载优先
    max_parallel_accounts: int = Field(
        default=2, ge=1, le=20
    )  # 单任务最多并行使用的账号数
    account_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20
    )  # 成员账号 id 列表（须均为当前用户账号）


class DouyinAccountPoolUpdate(SQLModel):
    """更新账号池的请求模型，所有字段可选。"""

    name: str | None = Field(default=None, min_length=1, max_length=80)  # 账号池名称
    description: str | None = Field(default=None, max_length=500)  # 账号池描述
    strategy: DouyinAccountPoolStrategy | None = None  # 调度策略
    max_parallel_accounts: int | None = Field(
        default=None, ge=1, le=20
    )  # 单任务最多并行账号数
    account_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=20
    )  # 成员账号 id 列表；传入时全量替换成员
    enabled: bool | None = None  # 是否启用


class DouyinAccountPool(SQLModel, table=True):
    """抖音账号池实体：将多个账号编组，按策略为采集任务批量分配账号。"""

    __tablename__ = "douyin_account_pool"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_douyin_account_pool_owner_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 账号池主键
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 id（外键 user.id，级联删除）
    name: str = Field(max_length=80, index=True)  # 账号池名称（同一用户内唯一）
    description: str = Field(default="", max_length=500)  # 账号池描述
    strategy: str = Field(
        default=DouyinAccountPoolStrategy.least_loaded.value, max_length=32
    )  # 调度策略（见 DouyinAccountPoolStrategy）
    max_parallel_accounts: int = Field(
        default=2, ge=1, le=20
    )  # 单任务最多并行使用的账号数
    rotation_cursor: int = Field(
        default=0, ge=0
    )  # 轮询游标，round_robin 策略下记录下次起始位置
    enabled: bool = Field(default=True, index=True)  # 是否启用
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 创建时间（UTC）
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 最近更新时间（UTC）


class DouyinAccountPoolMember(SQLModel, table=True):
    """账号池成员关系实体：记录账号与账号池的多对多绑定。"""

    __tablename__ = "douyin_account_pool_member"
    __table_args__ = (
        UniqueConstraint("pool_id", "account_id", name="uq_douyin_account_pool_member"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 成员关系主键
    pool_id: uuid.UUID = Field(
        foreign_key="douyin_account_pool.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )  # 所属账号池 id（外键 douyin_account_pool.id，级联删除）
    account_id: uuid.UUID = Field(
        foreign_key="douyin_account.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )  # 成员账号 id（外键 douyin_account.id，级联删除）
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 加入时间（UTC）


class DouyinAccountPoolPublic(SQLModel):
    """账号池对外响应模型（含成员账号摘要）。"""

    id: uuid.UUID  # 账号池 id
    name: str  # 账号池名称
    description: str  # 账号池描述
    strategy: DouyinAccountPoolStrategy  # 调度策略
    max_parallel_accounts: int  # 单任务最多并行账号数
    enabled: bool  # 是否启用
    accounts: list[DouyinAccountPublic]  # 成员账号列表（按优先级降序、名称升序）
    created_at: datetime  # 创建时间
    updated_at: datetime  # 最近更新时间


class DouyinAccountPoolsPublic(SQLModel):
    """账号池列表响应。"""

    data: list[DouyinAccountPoolPublic]  # 账号池列表
    count: int  # 账号池总数


class DouyinAccountLoginSessionPublic(SQLModel):
    """开启账号登录会话的响应模型。"""

    account: DouyinAccountPublic  # 账号信息
    status: DouyinAccountStatus  # 会话开启后的账号状态
    browser_mode: DouyinBrowserMode  # 浏览器运行模式
    viewer_url: str | None  # 可视化查看地址：远程为 noVNC，本机无（直接操作本机窗口）
    expires_at: datetime  # 登录会话过期时间
    message: str  # 面向用户的提示信息


class DouyinLocalBrowser(SQLModel, table=True):
    """本机浏览器实例：用户可在「浏览器管理」页自助增删的本地槽位。

    历史实现里本机槽位完全由 config.yaml / 环境变量派生（local-1 … local-N），
    用户在页面上无法扩展。改为落库后，槽位数量、端口与展示名都可在线维护：
    首次访问某用户时按配置物化默认槽位（默认 4 个），之后以库内数据为准。
    """

    __tablename__ = "douyin_local_browser"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_douyin_local_browser_owner_name"),
        UniqueConstraint("owner_id", "port", name="uq_douyin_local_browser_owner_port"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 槽位主键
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 id（槽位是用户私有资产）
    name: str = Field(max_length=64, index=True)  # 槽位名（如 local-5），Profile 目录名
    label: str = Field(max_length=80)  # 展示名称（默认「本机浏览器 N」）
    port: int = Field(ge=1, le=65535)  # CDP 调试端口（同一用户内唯一）
    enabled: bool = Field(default=True, index=True)  # 是否启用
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinAccountBrowser(SQLModel, table=True):
    """账号 ↔ 本机浏览器绑定：一个账号可以绑定多个本机浏览器实例。

    槽位与账号仍是「一个槽位同一时刻只服务一个账号」（一个 Profile 只能有一份
    登录态），但一个账号可以额外绑定多个槽位，便于同一身份在多台本机浏览器上
    并存使用。``DouyinAccount.slot`` 保留为主槽位（任务默认使用它）。
    """

    __tablename__ = "douyin_account_browser"
    __table_args__ = (
        UniqueConstraint("account_id", "slot_name", name="uq_douyin_account_browser"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(
        foreign_key="douyin_account.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    slot_name: str = Field(max_length=64, index=True)  # 绑定的本机槽位名
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )


class DouyinLocalBrowserPublic(SQLModel):
    """本机浏览器实例的对外模型（含占用账号与健康探测结果）。"""

    id: uuid.UUID  # 槽位主键
    name: str  # 槽位名（如 local-1）
    label: str  # 展示名称
    port: int  # CDP 调试端口
    enabled: bool  # 是否启用
    cdp_endpoint: str  # CDP 调试端点（host:port）
    in_use: bool  # 是否已被账号绑定（绑定中的槽位不允许删除）
    bound_account_ids: list[uuid.UUID]  # 绑定该槽位的账号 id 列表
    bound_account_names: list[str]  # 绑定该槽位的账号名称列表
    cdp_healthy: bool  # CDP 健康探测是否通过
    page_count: int  # 浏览器当前打开的页面数
    checked_at: datetime  # 本次探测时间
    created_at: datetime  # 创建时间


class DouyinLocalBrowsersPublic(SQLModel):
    """本机浏览器实例列表响应。"""

    data: list[DouyinLocalBrowserPublic]
    count: int


class DouyinLocalBrowserCreate(SQLModel):
    """新增本机浏览器实例的请求模型（槽位名与端口由服务端按顺序自动分配）。"""

    label: str | None = Field(default=None, max_length=80)  # 展示名称


class DouyinLocalBrowserUpdate(SQLModel):
    """更新本机浏览器实例的请求模型（端口随槽位名固定，不可单独修改）。"""

    label: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


class DouyinAccountBrowserBindRequest(SQLModel):
    """账号绑定本机浏览器实例的请求体（覆盖式：传入即最终绑定集合）。"""

    slot_names: list[str] = Field(default_factory=list, max_length=20)


class DouyinAccountBrowserBindResult(SQLModel):
    """账号本机浏览器绑定结果。"""

    account_id: uuid.UUID
    slot_names: list[str]  # 更新后的完整绑定集合


__all__ = [
    "DouyinBrowserMode",
    "DouyinAccountStatus",
    "DouyinAccountPoolStrategy",
    "DouyinAccountCreate",
    "DouyinAccountUpdate",
    "DouyinAccount",
    "DouyinAccountPublic",
    "DouyinAccountsPublic",
    "DouyinBrowserSlotPublic",
    "DouyinBrowserSlotsPublic",
    "DouyinLocalBrowser",
    "DouyinAccountBrowser",
    "DouyinLocalBrowserPublic",
    "DouyinLocalBrowsersPublic",
    "DouyinLocalBrowserCreate",
    "DouyinLocalBrowserUpdate",
    "DouyinAccountBrowserBindRequest",
    "DouyinAccountBrowserBindResult",
    "DouyinAccountPoolCreate",
    "DouyinAccountPoolUpdate",
    "DouyinAccountPool",
    "DouyinAccountPoolMember",
    "DouyinAccountPoolPublic",
    "DouyinAccountPoolsPublic",
    "DouyinAccountLoginSessionPublic",
]
