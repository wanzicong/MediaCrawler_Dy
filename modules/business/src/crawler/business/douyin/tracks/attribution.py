"""按关键词/达人当前赛道归属解析作品与评论的动态赛道条件。

采集任务记录保留创建时的赛道审计归属；内容查询则优先采用来源关键词、
其次采用达人名单的当前赛道。这样用户调整关键词或达人赛道后，历史作品与
评论会随业务对象出现在新赛道，同时未能识别来源的数据仍回退到任务赛道。
"""

from __future__ import annotations

import uuid
from typing import Any

from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.keywords.models import DouyinKeyword
from crawler.business.douyin.tasks.models import CrawlTask
from sqlalchemy import and_, func, or_
from sqlmodel import col, select


def content_attributed_track_id() -> Any:
    """返回作品当前归属赛道 ID 的相关标量表达式。

    归属优先级固定为：命中的关键词当前赛道 > 达人当前赛道 > 原任务赛道。
    子查询与外层 ``DouyinAweme``、``CrawlTask`` 相关，调用方必须已连接这两表。
    """
    normalized_source = func.lower(
        func.regexp_replace(
            func.btrim(col(DouyinAweme.source_keyword)),
            r"\s+",
            " ",
            "g",
        )
    )
    keyword_track_id = (
        select(col(DouyinKeyword.track_id))
        .where(
            CrawlTask.crawl_type == "search",
            DouyinKeyword.owner_id == CrawlTask.owner_id,
            DouyinKeyword.normalized_keyword == normalized_source,
        )
        .limit(1)
        .correlate(DouyinAweme, CrawlTask)
        .scalar_subquery()
    )

    creator_identity_match = or_(
        col(DouyinCreator.creator_hash) == col(DouyinAweme.creator_hash),
        col(DouyinCreator.creator_hash) == col(DouyinAweme.sec_uid),
        and_(
            col(DouyinAweme.creator_real_sec_uid) != "",
            col(DouyinCreator.sec_uid) == col(DouyinAweme.creator_real_sec_uid),
        ),
    )
    creator_track_id = (
        select(col(DouyinCreator.track_id))
        .where(
            DouyinCreator.owner_id == CrawlTask.owner_id,
            creator_identity_match,
        )
        .limit(1)
        .correlate(DouyinAweme, CrawlTask)
        .scalar_subquery()
    )
    return func.coalesce(
        keyword_track_id,
        creator_track_id,
        col(CrawlTask.track_id),
    )


def content_attributed_to_track(track_id: uuid.UUID) -> Any:
    """返回当前作品应归属于 ``track_id`` 的布尔表达式。"""
    return content_attributed_track_id() == track_id


__all__ = ["content_attributed_to_track", "content_attributed_track_id"]
