"""抖音接口请求日志限界上下文的业务模型与 API schema。

记录爬取过程中对抖音数据接口的每次调用：请求侧保留路径、参数与请求头全量，
响应侧只保留状态码与耗时，供查询页排查风控拦截与接口异常。
"""

import uuid
from datetime import datetime
from typing import Any

from crawler.business.common.models import get_datetime_utc
from sqlalchemy import JSON, DateTime, Index, Text
from sqlmodel import Field, SQLModel


class DouyinRequestLog(SQLModel, table=True):
    """抖音接口调用日志实体：每行对应一次对抖音数据接口的请求。"""

    __tablename__ = "douyin_request_log"
    __table_args__ = (
        Index("ix_douyin_request_log_owner_created", "owner_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)  # 日志 ID
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )  # 归属用户 ID（按用户隔离查询）
    task_id: uuid.UUID | None = Field(
        foreign_key="crawl_task.id", nullable=True, ondelete="SET NULL", index=True
    )  # 关联采集任务 ID；任务删除后保留日志但清空关联
    method: str = Field(max_length=16, index=True)  # HTTP 方法
    path: str = Field(max_length=500, index=True)  # 请求路径（不含查询串）
    url: str = Field(sa_type=Text)  # 完整请求地址
    query_params: dict[str, Any] = Field(
        default_factory=dict, sa_type=JSON
    )  # 签名后的完整查询参数
    request_headers: dict[str, Any] = Field(
        default_factory=dict, sa_type=JSON
    )  # 实际发送的全部请求头
    request_body: dict[str, Any] | None = Field(
        default=None, sa_type=JSON
    )  # POST 表单数据（签名后），GET 为 None
    response_status: int | None = Field(
        default=None, index=True
    )  # 响应状态码；网络异常时为 None
    duration_ms: int = Field(default=0)  # 请求耗时（毫秒）
    error: str | None = Field(default=None, sa_type=Text)  # 异常类型名；成功时为 None
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
    )  # 记录时间


class DouyinRequestLogPublic(SQLModel):
    """单条抖音请求日志的对外模型（响应体永不落库）。"""

    id: uuid.UUID  # 日志 ID
    task_id: uuid.UUID | None  # 关联任务 ID
    method: str  # HTTP 方法
    path: str  # 请求路径
    url: str  # 完整请求地址
    query_params: dict[str, Any]  # 查询参数
    request_headers: dict[str, Any]  # 请求头全量
    request_body: dict[str, Any] | None  # 请求体
    response_status: int | None  # 响应状态码
    duration_ms: int  # 请求耗时
    error: str | None  # 异常类型名
    created_at: datetime  # 记录时间


class DouyinRequestLogsPublic(SQLModel):
    """抖音请求日志分页列表的对外模型。"""

    data: list[DouyinRequestLogPublic]  # 当前页数据
    count: int  # 满足条件的总条数


__all__ = [
    "DouyinRequestLog",
    "DouyinRequestLogPublic",
    "DouyinRequestLogsPublic",
]
