# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""爬取任务持久化适配层。

基于 SQLModel/PostgreSQL 落盘任务、分片、作品、评论与用户行为数据；
对外提供 async 接口，内部经 asyncio.to_thread 执行同步 SQLAlchemy 操作。
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from crawler.bootstrap.database import engine
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import (
    DouyinAweme,
    DouyinUserAction,
)
from crawler.business.douyin.tags.service import extract_hashtags, sync_aweme_tags
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
    CrawlTaskShard,
    CrawlTaskShardStatus,
    CrawlTaskStatus,
)
from crawler.douyin_client.privacy import map_aweme, map_comment
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, func, select


class DouyinStorage:
    """抽取后爬虫使用的 SQLModel/PostgreSQL 持久化适配器（按任务，可选按分片）。"""

    def __init__(self, task_id: uuid.UUID, shard_id: uuid.UUID | None = None):
        """初始化存储适配器。

        参数：task_id 任务 ID；shard_id 分片 ID（多账号分片执行时传入，断点与计数落到分片）。
        """
        self.task_id = task_id
        self.shard_id = shard_id

    @staticmethod
    async def create_task(owner_id: uuid.UUID, request: CrawlTaskCreate) -> CrawlTask:
        """创建任务记录：解析归属赛道、写入请求快照与初始断点，并同步搜索关键词。

        参数：owner_id 归属用户 ID；request 任务创建请求。
        返回：新创建的任务实体。
        """
        return await asyncio.to_thread(
            DouyinStorage._create_task_sync, owner_id, request
        )

    @staticmethod
    def _create_task_sync(owner_id: uuid.UUID, request: CrawlTaskCreate) -> CrawlTask:
        """create_task 的同步实现（在线程池中执行）。"""
        with Session(engine) as session:
            from crawler.business.douyin.tracks.bindings import (
                assign_task_track,
                resolve_track,
            )

            track = resolve_track(
                session,
                owner_id=owner_id,
                track_id=request.track_id,
            )
            stored_request = request.model_copy(update={"track_id": track.id})
            task = CrawlTask(
                owner_id=owner_id,
                track_id=track.id,
                account_id=request.account_id,
                account_pool_id=request.account_pool_id,
                account_strategy=request.account_strategy.value,
                crawl_type=request.crawl_type.value,
                status=CrawlTaskStatus.queued.value,
                request_json=json.dumps(
                    stored_request.public_request(), ensure_ascii=False
                ),
                checkpoint_json=json.dumps(
                    {
                        "version": 1,
                        "phase": CrawlTaskPhase.crawl.value,
                        "crawl_type": request.crawl_type.value,
                        "position": {},
                    },
                    ensure_ascii=False,
                ),
            )
            session.add(task)
            session.flush()
            assign_task_track(session, task=task, track=track)
            if request.keywords:
                from crawler.business.douyin.keywords.service import (
                    sync_task_keywords_in_session,
                )

                sync_task_keywords_in_session(
                    session,
                    task_id=task.id,
                    owner_id=owner_id,
                    values=request.keywords,
                    track_id=track.id,
                )
            session.commit()
            session.refresh(task)
            return task

    @staticmethod
    async def get_task(task_id: uuid.UUID) -> CrawlTask | None:
        """按 ID 读取任务（返回已脱离会话的实体，可跨请求使用）。"""
        return await asyncio.to_thread(DouyinStorage._get_task_sync, task_id)

    @staticmethod
    def _get_task_sync(task_id: uuid.UUID) -> CrawlTask | None:
        """get_task 的同步实现。"""
        with Session(engine) as session:
            task = session.get(CrawlTask, task_id)
            if task is not None:
                session.expunge(task)
            return task

    async def update_task(self, **values: Any) -> None:
        """更新任务字段；值为 CrawlTaskStatus 枚举时自动转为其值。任务不存在时抛出 KeyError。"""
        await asyncio.to_thread(self._update_task_sync, values)

    def _update_task_sync(self, values: dict[str, Any]) -> None:
        """update_task 的同步实现。"""
        normalized = {
            key: (value.value if isinstance(value, CrawlTaskStatus) else value)
            for key, value in values.items()
        }
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.sqlmodel_update(normalized)
            session.add(task)
            session.commit()

    async def load_checkpoint(self) -> dict[str, Any]:
        """读取断点检查点；分片存储读分片自己的检查点，字段缺失或损坏时回退默认值。

        返回：规范化后的检查点字典（version/phase/crawl_type/position）。
        异常：KeyError —— 任务或分片不存在。
        """
        return await asyncio.to_thread(self._load_checkpoint_sync)

    def _load_checkpoint_sync(self) -> dict[str, Any]:
        """load_checkpoint 的同步实现。"""
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            checkpoint_json = task.checkpoint_json
            if self.shard_id is not None:
                shard = session.get(CrawlTaskShard, self.shard_id)
                if shard is None or shard.task_id != self.task_id:
                    raise KeyError(f"Douyin task shard not found: {self.shard_id}")
                checkpoint_json = shard.checkpoint_json
            try:
                checkpoint = json.loads(checkpoint_json or "{}")
            except json.JSONDecodeError:
                checkpoint = {}
            if not isinstance(checkpoint, dict):
                checkpoint = {}
            phase = checkpoint.get("phase")
            if phase not in {item.value for item in CrawlTaskPhase}:
                phase = (
                    CrawlTaskPhase.completed.value
                    if task.status == CrawlTaskStatus.succeeded.value
                    else CrawlTaskPhase.crawl.value
                )
            position = checkpoint.get("position")
            return {
                "version": 1,
                "phase": phase,
                "crawl_type": str(checkpoint.get("crawl_type") or task.crawl_type),
                "position": position if isinstance(position, dict) else {},
            }

    async def save_checkpoint(
        self,
        *,
        phase: CrawlTaskPhase,
        crawl_type: str,
        position: dict[str, Any] | None = None,
    ) -> None:
        """保存断点检查点（覆盖式写入 version/phase/crawl_type/position）。

        参数：phase 当前阶段；crawl_type 爬取类型；position 爬取位置明细（可选）。
        异常：KeyError —— 任务或分片不存在。
        """
        checkpoint = {
            "version": 1,
            "phase": phase.value,
            "crawl_type": crawl_type,
            "position": position or {},
        }
        await asyncio.to_thread(self._save_checkpoint_sync, checkpoint)

    def _save_checkpoint_sync(self, checkpoint: dict[str, Any]) -> None:
        """save_checkpoint 的同步实现（分片存储写入分片记录）。"""
        with Session(engine) as session:
            if self.shard_id is not None:
                shard = session.get(CrawlTaskShard, self.shard_id)
                if shard is None or shard.task_id != self.task_id:
                    raise KeyError(f"Douyin task shard not found: {self.shard_id}")
                shard.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
                session.add(shard)
                session.commit()
                return
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            session.add(task)
            session.commit()

    async def complete_task(self, crawl_type: str) -> CrawlTask:
        """标记任务成功完成：写入 completed 断点并清理错误/二维码。

        参数：crawl_type 爬取类型（写入断点）。
        返回：更新后的任务实体。
        """
        return await asyncio.to_thread(self._complete_task_sync, crawl_type)

    def _complete_task_sync(self, crawl_type: str) -> CrawlTask:
        """complete_task 的同步实现。"""
        checkpoint = {
            "version": 1,
            "phase": CrawlTaskPhase.completed.value,
            "crawl_type": crawl_type,
            "position": {},
        }
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            task.status = CrawlTaskStatus.succeeded.value
            task.error = None
            task.qrcode_path = None
            task.finished_at = get_datetime_utc()
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

    async def mark_resumed(
        self,
        status: CrawlTaskStatus,
        *,
        phase: CrawlTaskPhase | None = None,
        crawl_type: str | None = None,
    ) -> CrawlTask:
        """把任务重置为可再次执行的状态：累计恢复次数、清空错误与结束时间。

        参数：status 目标状态（通常为 queued）；phase 传入时同时重置断点阶段；
              crawl_type 重置断点时使用的爬取类型。
        返回：更新后的任务实体。
        """
        return await asyncio.to_thread(
            self._mark_resumed_sync,
            status,
            phase,
            crawl_type,
        )

    def _mark_resumed_sync(
        self,
        status: CrawlTaskStatus,
        phase: CrawlTaskPhase | None = None,
        crawl_type: str | None = None,
    ) -> CrawlTask:
        """mark_resumed 的同步实现。"""
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            if phase is not None:
                task.checkpoint_json = json.dumps(
                    {
                        "version": 1,
                        "phase": phase.value,
                        "crawl_type": crawl_type or task.crawl_type,
                        "position": {},
                    },
                    ensure_ascii=False,
                )
            task.status = status.value
            task.resume_count += 1
            task.last_resumed_at = get_datetime_utc()
            task.finished_at = None
            task.error = None
            task.qrcode_path = None
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

    async def prepare_media_processing(self, request: CrawlTaskCreate) -> CrawlTask:
        """为独立媒体处理准备任务：更新请求快照、断点置为 media 阶段并重置为排队状态。

        参数：request 媒体批处理请求快照。
        返回：更新后的任务实体。
        """
        return await asyncio.to_thread(self._prepare_media_processing_sync, request)

    def _prepare_media_processing_sync(self, request: CrawlTaskCreate) -> CrawlTask:
        """prepare_media_processing 的同步实现。"""
        checkpoint = {
            "version": 1,
            "phase": CrawlTaskPhase.media.value,
            "crawl_type": request.crawl_type.value,
            "position": {},
        }
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if task is None:
                raise KeyError(f"Douyin task not found: {self.task_id}")
            task.request_json = json.dumps(request.public_request(), ensure_ascii=False)
            task.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False)
            # 状态由 runner 真正开始执行后才切为 processing_media；此处保持 queued，
            # 避免仍在等待调度的任务被误认为已经在处理。
            task.status = CrawlTaskStatus.queued.value
            task.resume_count += 1
            task.last_resumed_at = get_datetime_utc()
            task.finished_at = None
            task.error = None
            task.qrcode_path = None
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

    @staticmethod
    async def mark_active_tasks_interrupted() -> None:
        """服务重启恢复：把残留的活动状态任务标记为中断（断点已完成阶段的标记为成功）。"""
        await asyncio.to_thread(DouyinStorage._mark_active_tasks_interrupted_sync)

    @staticmethod
    def _mark_active_tasks_interrupted_sync() -> None:
        """mark_active_tasks_interrupted 的同步实现。"""
        active = {
            CrawlTaskStatus.queued.value,
            CrawlTaskStatus.waiting_login.value,
            CrawlTaskStatus.running.value,
            CrawlTaskStatus.processing_media.value,
            CrawlTaskStatus.cancelling.value,
        }
        now = get_datetime_utc()
        with Session(engine) as session:
            tasks = session.exec(
                select(CrawlTask).where(col(CrawlTask.status).in_(active))
            ).all()
            for task in tasks:
                try:
                    checkpoint = json.loads(task.checkpoint_json or "{}")
                except json.JSONDecodeError:
                    checkpoint = {}
                completed = bool(
                    isinstance(checkpoint, dict)
                    and checkpoint.get("phase") == CrawlTaskPhase.completed.value
                    and task.status != CrawlTaskStatus.processing_media.value
                )
                task.status = (
                    CrawlTaskStatus.succeeded.value
                    if completed
                    else CrawlTaskStatus.interrupted.value
                )
                task.error = None if completed else "API 服务重启，任务已中断"
                task.finished_at = now
                task.qrcode_path = None
                session.add(task)
            session.commit()

    async def save_aweme(self, item: dict[str, Any], *, source_keyword: str) -> bool:
        """映射并保存一条作品（含话题标签同步与计数刷新）。

        参数：item 抖音原始作品数据；source_keyword 来源关键词/类型标记。
        返回：是否为首次入库的新作品。
        """
        mapped = map_aweme(item, source_keyword)
        if not mapped["aweme_id"]:
            return False
        tag_names = extract_hashtags(item)
        return await asyncio.to_thread(self._save_aweme_sync, mapped, tag_names)

    def _save_aweme_sync(
        self, mapped: dict[str, Any], tag_names: list[str] | None = None
    ) -> bool:
        """save_aweme 的同步实现：按 (task_id, aweme_id) 幂等 upsert，并维护分片与任务计数。"""
        values = {"id": uuid.uuid4(), "task_id": self.task_id, **mapped}
        statement = insert(DouyinAweme).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_douyin_aweme_task_aweme",
            set_={
                key: value for key, value in mapped.items() if key not in {"aweme_id"}
            }
            | {"fetched_at": get_datetime_utc()},
        )
        with Session(engine) as session:
            existed = session.exec(
                select(DouyinAweme.id).where(
                    DouyinAweme.task_id == self.task_id,
                    DouyinAweme.aweme_id == mapped["aweme_id"],
                )
            ).first()
            session.execute(statement)
            aweme_record_id = session.exec(
                select(DouyinAweme.id).where(
                    DouyinAweme.task_id == self.task_id,
                    DouyinAweme.aweme_id == mapped["aweme_id"],
                )
            ).one()
            sync_aweme_tags(
                session,
                task_id=self.task_id,
                aweme_record_id=aweme_record_id,
                tag_names=tag_names
                or extract_hashtags(str(mapped.get("description") or "")),
            )
            session.commit()
            if existed is None and self.shard_id is not None:
                shard = session.get(CrawlTaskShard, self.shard_id)
                if shard is not None:
                    shard.aweme_count += 1
                    session.add(shard)
                    session.commit()
            self._refresh_counts(session)
            return existed is None

    async def aweme_ids(self) -> set[str]:
        """返回任务已采集的全部 aweme_id 集合（用于增量去重）。"""
        return await asyncio.to_thread(self._aweme_ids_sync)

    def _aweme_ids_sync(self) -> set[str]:
        """aweme_ids 的同步实现。"""
        with Session(engine) as session:
            return set(
                session.exec(
                    select(DouyinAweme.aweme_id).where(
                        DouyinAweme.task_id == self.task_id
                    )
                ).all()
            )

    async def comment_counts(self, aweme_ids: list[str]) -> dict[str, int]:
        """统计指定作品已落库的评论数。

        参数：aweme_ids 作品 ID 列表。
        返回：aweme_id -> 已存评论数 的映射。
        """
        if not aweme_ids:
            return {}
        return await asyncio.to_thread(self._comment_counts_sync, aweme_ids)

    def _comment_counts_sync(self, aweme_ids: list[str]) -> dict[str, int]:
        """comment_counts 的同步实现。"""
        with Session(engine) as session:
            rows = session.exec(
                select(DouyinComment.aweme_id, func.count())
                .where(
                    DouyinComment.task_id == self.task_id,
                    col(DouyinComment.aweme_id).in_(set(aweme_ids)),
                )
                .group_by(DouyinComment.aweme_id)
            ).all()
            return {aweme_id: int(count) for aweme_id, count in rows}

    async def save_comments(self, aweme_id: str, items: list[dict[str, Any]]) -> None:
        """映射并批量保存评论（供客户端回调按页调用）。

        参数：aweme_id 评论所属作品；items 原始评论数据列表。
        """
        mapped = [value for item in items if (value := map_comment(item, aweme_id))]
        if mapped:
            await asyncio.to_thread(self._save_comments_sync, mapped)

    def _save_comments_sync(self, mapped_items: list[dict[str, Any]]) -> None:
        """save_comments 的同步实现：按 (task_id, comment_id) 幂等 upsert，并维护分片与任务计数。"""
        with Session(engine) as session:
            inserted = 0
            for mapped in mapped_items:
                existed = session.exec(
                    select(DouyinComment.id).where(
                        DouyinComment.task_id == self.task_id,
                        DouyinComment.comment_id == mapped["comment_id"],
                    )
                ).first()
                values = {"id": uuid.uuid4(), "task_id": self.task_id, **mapped}
                statement = insert(DouyinComment).values(**values)
                statement = statement.on_conflict_do_update(
                    constraint="uq_douyin_comment_task_comment",
                    set_={
                        key: value
                        for key, value in mapped.items()
                        if key not in {"comment_id"}
                    }
                    | {"fetched_at": get_datetime_utc()},
                )
                session.execute(statement)
                inserted += int(existed is None)
            session.commit()
            if inserted and self.shard_id is not None:
                shard = session.get(CrawlTaskShard, self.shard_id)
                if shard is not None:
                    shard.comment_count += inserted
                    session.add(shard)
                    session.commit()
            self._refresh_counts(session)

    async def save_action(
        self, account_hash: str, aweme_id: str, action_type: str
    ) -> None:
        """记录一条点赞/收藏行为（按任务+账号哈希+作品+类型幂等，重复时仅刷新观测时间）。

        参数：account_hash 匿名化账号标识；aweme_id 作品 ID；action_type 行为类型。
        """
        await asyncio.to_thread(
            self._save_action_sync, account_hash, aweme_id, action_type
        )

    def _save_action_sync(
        self, account_hash: str, aweme_id: str, action_type: str
    ) -> None:
        """save_action 的同步实现。"""
        values = {
            "id": uuid.uuid4(),
            "task_id": self.task_id,
            "account_hash": account_hash,
            "aweme_id": aweme_id,
            "action_type": action_type,
            "observed_at": get_datetime_utc(),
        }
        statement = insert(DouyinUserAction).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_douyin_action_task_account_aweme_type",
            set_={"observed_at": values["observed_at"]},
        )
        with Session(engine) as session:
            session.execute(statement)
            session.commit()
            self._refresh_counts(session)

    def _refresh_counts(self, session: Session) -> None:
        """重新统计并回写任务的作品/评论/行为冗余计数。"""
        aweme_count = session.exec(
            select(func.count())
            .select_from(DouyinAweme)
            .where(DouyinAweme.task_id == self.task_id)
        ).one()
        comment_count = session.exec(
            select(func.count())
            .select_from(DouyinComment)
            .where(DouyinComment.task_id == self.task_id)
        ).one()
        action_count = session.exec(
            select(func.count())
            .select_from(DouyinUserAction)
            .where(DouyinUserAction.task_id == self.task_id)
        ).one()
        task = session.get(CrawlTask, self.task_id)
        if task is None:
            raise KeyError(f"Douyin task not found: {self.task_id}")
        task.aweme_count = aweme_count
        task.comment_count = comment_count
        task.action_count = action_count
        session.add(task)
        session.commit()

    async def counts(self) -> tuple[int, int, int]:
        """读取任务的 (作品数, 评论数, 行为数) 冗余计数；任务不存在时返回全零。"""
        return await asyncio.to_thread(self._counts_sync)

    def _counts_sync(self) -> tuple[int, int, int]:
        """counts 的同步实现。"""
        with Session(engine) as session:
            task = session.get(CrawlTask, self.task_id)
            if not task:
                return 0, 0, 0
            return task.aweme_count, task.comment_count, task.action_count

    @staticmethod
    async def create_shards(
        task_id: uuid.UUID,
        assignments: list[tuple[uuid.UUID, CrawlTaskCreate]],
    ) -> list[CrawlTaskShard]:
        """重建任务的全部分片记录（先删除旧分片再按账号分配写入）。

        参数：task_id 任务 ID；assignments (账号 ID, 分片请求) 列表。
        返回：新创建的分片实体列表。
        """
        return await asyncio.to_thread(
            DouyinStorage._create_shards_sync, task_id, assignments
        )

    @staticmethod
    def _create_shards_sync(
        task_id: uuid.UUID,
        assignments: list[tuple[uuid.UUID, CrawlTaskCreate]],
    ) -> list[CrawlTaskShard]:
        """create_shards 的同步实现。"""
        with Session(engine) as session:
            existing = session.exec(
                select(CrawlTaskShard).where(CrawlTaskShard.task_id == task_id)
            ).all()
            for shard in existing:
                session.delete(shard)
            session.flush()
            shards: list[CrawlTaskShard] = []
            for index, (account_id, request) in enumerate(assignments):
                shard = CrawlTaskShard(
                    task_id=task_id,
                    account_id=account_id,
                    shard_index=index,
                    status=CrawlTaskShardStatus.queued.value,
                    request_json=json.dumps(
                        request.public_request(), ensure_ascii=False
                    ),
                    checkpoint_json=json.dumps(
                        {
                            "version": 1,
                            "phase": CrawlTaskPhase.crawl.value,
                            "crawl_type": request.crawl_type.value,
                            "position": {},
                        },
                        ensure_ascii=False,
                    ),
                )
                session.add(shard)
                shards.append(shard)
            session.commit()
            for shard in shards:
                session.refresh(shard)
                session.expunge(shard)
            return shards

    @staticmethod
    async def update_shard(shard_id: uuid.UUID, **values: Any) -> None:
        """更新分片字段；值为 CrawlTaskShardStatus 枚举时自动转为其值。分片不存在时抛出 KeyError。"""
        await asyncio.to_thread(DouyinStorage._update_shard_sync, shard_id, values)

    @staticmethod
    def _update_shard_sync(shard_id: uuid.UUID, values: dict[str, Any]) -> None:
        """update_shard 的同步实现。"""
        normalized = {
            key: (value.value if isinstance(value, CrawlTaskShardStatus) else value)
            for key, value in values.items()
        }
        with Session(engine) as session:
            shard = session.get(CrawlTaskShard, shard_id)
            if shard is None:
                raise KeyError(f"Douyin task shard not found: {shard_id}")
            shard.sqlmodel_update(normalized)
            session.add(shard)
            session.commit()


def task_public_values(task: CrawlTask) -> dict[str, Any]:
    """由任务实体提取对外展示所需的公共字段字典。

    解析请求快照与断点（损坏时回退默认值），推断断点阶段、爬取/媒体可恢复性
    与二维码可用性。

    参数：task 任务实体。
    返回：构造 CrawlTaskPublic 所需的字段字典（不含赛道与代表性作品字段）。
    """
    qrcode = Path(task.qrcode_path) if task.qrcode_path else None
    try:
        request = json.loads(task.request_json)
    except json.JSONDecodeError:
        request = {}
    if not isinstance(request, dict):
        request = {}
    request["track_id"] = str(task.track_id)
    try:
        checkpoint = json.loads(task.checkpoint_json or "{}")
    except json.JSONDecodeError:
        checkpoint = {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    raw_phase = checkpoint.get("phase")
    if raw_phase not in {phase.value for phase in CrawlTaskPhase}:
        raw_phase = (
            CrawlTaskPhase.completed.value
            if task.status == CrawlTaskStatus.succeeded.value
            else CrawlTaskPhase.crawl.value
        )
    phase = CrawlTaskPhase(raw_phase)
    terminal = task.status in {
        CrawlTaskStatus.succeeded.value,
        CrawlTaskStatus.failed.value,
        CrawlTaskStatus.cancelled.value,
        CrawlTaskStatus.interrupted.value,
    }
    return {
        "id": task.id,
        "owner_id": task.owner_id,
        "account_id": task.account_id,
        "account_pool_id": task.account_pool_id,
        "account_strategy": task.account_strategy,
        "crawl_type": task.crawl_type,
        "status": task.status,
        "request": request,
        "aweme_count": task.aweme_count,
        "comment_count": task.comment_count,
        "action_count": task.action_count,
        "checkpoint_phase": phase,
        "resume_count": task.resume_count,
        "can_resume_crawl": bool(
            task.status
            in {
                CrawlTaskStatus.failed.value,
                CrawlTaskStatus.cancelled.value,
                CrawlTaskStatus.interrupted.value,
            }
            and phase == CrawlTaskPhase.crawl
        ),
        "can_resume_media": bool(terminal and request.get("download_media")),
        "error": task.error,
        "has_qrcode": bool(qrcode and qrcode.is_file()),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "last_resumed_at": task.last_resumed_at,
    }
