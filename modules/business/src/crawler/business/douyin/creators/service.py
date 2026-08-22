"""抖音达人名单的写侧应用服务。

覆盖达人名单的增删改查、主页链接解析与去重、达人-任务绑定同步
（自动/手动/历史回填），以及基于达人批量创建采集任务（每达人一个
独立任务，与关键词库的独立模式对齐）。服务层错误统一以
CreatorServiceError 体系抛出，由 HTTP 适配层翻译。

达人名单是用户主动维护的采集目标（与关键词一致，属用户资产），
sec_uid 明文存储；creator_hash 为脱敏哈希（对 sec_uid 做 SHA-256
并截取前 16 位），与采集作品数据 douyin_aweme.sec_uid 匹配，
用于聚合作品数与作品深链。
"""

import json
import uuid
from collections import defaultdict

from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.creators.models import (
    DouyinAwemeSyncResult,
    DouyinCreator,
    DouyinCreatorBatchTaskRequest,
    DouyinCreatorBulkCreateResult,
    DouyinCreatorPublic,
    DouyinCreatorStatus,
    DouyinCreatorSyncResult,
    DouyinCreatorTaskBatchResult,
    DouyinCreatorTaskLink,
)
from crawler.business.douyin.keywords.models import DouyinKeywordSyncSource
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskStatus,
    DouyinCrawlType,
)
from crawler.business.douyin.tracks.models import DouyinTrack
from crawler.douyin_client.privacy import anonymize_user_id
from crawler.douyin_client.types import parse_creator_info
from sqlmodel import Session, col, func, select

# 视为「进行中」的任务状态集合，用于推导达人的 active 状态
ACTIVE_TASK_STATUSES = {
    CrawlTaskStatus.queued.value,
    CrawlTaskStatus.waiting_login.value,
    CrawlTaskStatus.running.value,
    CrawlTaskStatus.processing_media.value,
    CrawlTaskStatus.cancelling.value,
}
# 视为「失败」的任务状态集合，用于推导达人的 failed 状态
FAILED_TASK_STATUSES = {
    CrawlTaskStatus.failed.value,
    CrawlTaskStatus.cancelled.value,
    CrawlTaskStatus.interrupted.value,
}


class CreatorServiceError(Exception):
    """达人服务错误基类，由 HTTP 适配层统一翻译为响应。"""


class CreatorNotFoundError(CreatorServiceError):
    """达人（或关联资源）不存在，或按 not-found 语义屏蔽的无权访问。"""


class CreatorPermissionDeniedError(CreatorServiceError):
    """当前用户无权操作该达人（属于其他用户且非超管）。"""


class CreatorValidationError(CreatorServiceError, ValueError):
    """达人相关请求参数校验失败。"""


class CreatorConflictError(CreatorServiceError):
    """达人操作与现有数据冲突（如目标赛道已停用等）。"""


def get_creator_for_actor(
    session: Session,
    *,
    creator_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinCreator:
    """按 ID 获取达人并校验操作者权限。

    参数：
        session: 数据库会话。
        creator_id: 达人 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管（超管可操作任意用户的达人）。

    返回：
        达人实体。

    异常：
        CreatorNotFoundError: 达人不存在。
        CreatorPermissionDeniedError: 达人属于其他用户且非超管。
    """
    item = session.get(DouyinCreator, creator_id)
    if item is None:
        raise CreatorNotFoundError("达人不存在")
    if item.owner_id != actor_id and not is_superuser:
        raise CreatorPermissionDeniedError("Not enough permissions")
    return item


def get_task_for_actor(
    session: Session,
    *,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> CrawlTask:
    """按 ID 获取采集任务并校验操作者权限。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    返回：
        采集任务实体。

    异常：
        CreatorNotFoundError: 任务不存在。
        CreatorPermissionDeniedError: 任务属于其他用户且非超管。
    """
    task = session.get(CrawlTask, task_id)
    if task is None:
        raise CreatorNotFoundError("抖音任务不存在")
    if task.owner_id != actor_id and not is_superuser:
        raise CreatorPermissionDeniedError("Not enough permissions")
    return task


def parse_creator_targets(values: list[str]) -> list[str]:
    """清洗达人目标列表：主页链接转为 sec_user_id，去重并保持输入顺序。

    参数：
        values: 用户输入的达人主页链接或 sec_user_id 列表。

    返回：
        sec_user_id 列表，保持输入顺序。

    异常：
        CreatorValidationError: 某个目标无法解析，或清洗后无有效目标。
    """
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        try:
            info = parse_creator_info(raw)
        except ValueError as exc:
            raise CreatorValidationError(str(exc)) from exc
        sec_uid = info.sec_user_id
        if not sec_uid or len(sec_uid) > 256 or sec_uid in seen:
            continue
        seen.add(sec_uid)
        result.append(sec_uid)
    if not result:
        raise CreatorValidationError("请至少提供一个有效的达人主页链接或 sec_user_id")
    return result


def create_creators(
    session: Session,
    *,
    owner_id: uuid.UUID,
    creators: list[str],
    notes: str = "",
    enabled: bool = True,
    track_id: uuid.UUID | None = None,
    move_existing: bool = True,
) -> tuple[list[DouyinCreator], int, int]:
    """批量创建达人（已存在则复用），并将达人归属到目标赛道。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        owner_id: 归属用户 ID。
        creators: 达人主页链接或 sec_user_id 列表。
        notes: 新建达人写入的备注。
        enabled: 新建达人的启用状态。
        track_id: 目标赛道 ID，None 时使用默认赛道。
        move_existing: 已存在的达人是否允许移动到目标赛道。

    返回：
        三元组 (达人实体列表, 新建数量, 复用已存在数量)。

    异常：
        CreatorNotFoundError: 目标赛道不存在或无权访问。
        CreatorConflictError: 目标赛道已停用。
        CreatorValidationError: 目标解析失败或其他参数非法。
    """
    from crawler.business.douyin.tracks.bindings import resolve_track

    try:
        track = resolve_track(session, owner_id=owner_id, track_id=track_id)
    except ValueError as exc:
        message = str(exc)
        if "不存在" in message or "无权访问" in message:
            raise CreatorNotFoundError(message) from exc
        if "停用" in message:
            raise CreatorConflictError(message) from exc
        raise CreatorValidationError(message) from exc
    cleaned = parse_creator_targets(creators)
    existing_rows = session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            col(DouyinCreator.sec_uid).in_(cleaned),
        )
    ).all()
    by_sec_uid = {item.sec_uid: item for item in existing_rows}
    created = 0
    output: list[DouyinCreator] = []
    for sec_uid in cleaned:
        item = by_sec_uid.get(sec_uid)
        if item is None:
            item = DouyinCreator(
                owner_id=owner_id,
                track_id=track.id,
                sec_uid=sec_uid,
                creator_hash=anonymize_user_id(sec_uid),
                notes=notes.strip(),
                enabled=enabled,
            )
            session.add(item)
            session.flush()
            by_sec_uid[sec_uid] = item
            created += 1
        if item.track_id != track.id and move_existing:
            item.track_id = track.id
            session.add(item)
        output.append(item)
    return output, created, len(output) - created


def create_creator_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    creators: list[str],
    notes: str,
    enabled: bool,
    track_id: uuid.UUID | None = None,
) -> DouyinCreatorBulkCreateResult:
    """批量创建达人并提交事务，返回新建/复用统计与完整公开模型。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。
        creators: 达人主页链接或 sec_user_id 列表。
        notes: 新建达人写入的备注。
        enabled: 新建达人的启用状态。
        track_id: 目标赛道 ID，None 时使用默认赛道。

    返回：
        批量创建结果（含达人列表、新建数与复用数）。

    异常：
        CreatorNotFoundError: 目标赛道不存在或无权访问。
        CreatorConflictError: 目标赛道已停用。
        CreatorValidationError: 达人目标解析失败。
    """
    items, created, existing = create_creators(
        session,
        owner_id=owner_id,
        creators=creators,
        notes=notes,
        enabled=enabled,
        track_id=track_id,
    )
    session.commit()
    rows = build_creator_public_rows(session, owner_id=owner_id)
    by_id = {item.id: item for item in rows}
    return DouyinCreatorBulkCreateResult(
        data=[by_id[item.id] for item in items],
        created_count=created,
        existing_count=existing,
    )


def import_aweme_creators(
    session: Session,
    *,
    owner_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
) -> DouyinAwemeSyncResult:
    """从采集作品聚合导入达人（含正式与占位）并提交事务。

    聚合规则：按 (任务赛道, 作品脱敏 sec_uid) 分组统计作品数与最新
    昵称；同一脱敏身份出现在多个赛道时归入作品数最多的赛道。
    task_id 传入时仅聚合该任务的作品（任务赛道即归属赛道）。

    导入分流：带真实 sec_uid（creator_real_sec_uid）的新采集作品
    直接创建/升级为正式达人（可立即创建任务）；仅含脱敏哈希的历史
    作品创建占位达人（待补全主页链接后转正）。与名单中已有达人
    （按 creator_hash 或真实 sec_uid 匹配）重合的跳过。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。
        task_id: 限定聚合范围的任务 ID；省略时聚合该用户全部历史作品。

    返回：
        导入结果统计（去重达人数、新建数、已存在数）。
    """
    query = (
        select(  # type: ignore[call-overload]  # SQLModel 存根仅声明到四列
            col(CrawlTask.track_id),
            col(DouyinAweme.sec_uid),
            func.max(col(DouyinAweme.nickname)),
            func.count(col(DouyinAweme.id)),
            func.max(col(DouyinAweme.creator_real_sec_uid)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(
            CrawlTask.owner_id == owner_id,
            col(DouyinAweme.sec_uid) != "",
        )
        .group_by(col(CrawlTask.track_id), col(DouyinAweme.sec_uid))
    )
    if task_id is not None:
        query = query.where(col(DouyinAweme.task_id) == task_id)
    rows = session.exec(query).all()
    best: dict[str, tuple[uuid.UUID | None, str, str, int]] = {}
    for track_id, sec_uid, nickname, count, real_uid in rows:
        current = best.get(sec_uid)
        if current is None or int(count) > current[3]:
            best[sec_uid] = (
                track_id,
                str(nickname or ""),
                str(real_uid or ""),
                int(count),
            )
    if not best:
        return DouyinAwemeSyncResult(total_count=0, created_count=0, existing_count=0)
    existing = session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            col(DouyinCreator.creator_hash).in_(best.keys()),
        )
    ).all()
    existing_hashes = {item.creator_hash for item in existing}
    placeholders_by_hash = {
        item.creator_hash: item for item in existing if item.is_placeholder
    }
    real_uids = {info[2] for info in best.values() if info[2]}
    real_uid_taken = set(
        session.exec(
            select(DouyinCreator.sec_uid).where(
                DouyinCreator.owner_id == owner_id,
                col(DouyinCreator.sec_uid).in_(real_uids),
            )
        ).all()
    )
    created = 0
    skipped = 0
    for sec_uid_hash, (track_id, nickname, real_uid, _count) in best.items():
        if real_uid:
            if real_uid in real_uid_taken:
                continue
            placeholder = placeholders_by_hash.get(sec_uid_hash)
            if placeholder is not None:
                # 同一达人的真实标识已采集到：占位直接升级为正式
                placeholder.sec_uid = real_uid
                placeholder.is_placeholder = False
                placeholder.nickname = nickname or placeholder.nickname
                placeholder.notes = "由历史采集作品自动导入"
                session.add(placeholder)
                real_uid_taken.add(real_uid)
                created += 1
                continue
            if track_id is None:
                skipped += 1
                continue
            session.add(
                DouyinCreator(
                    owner_id=owner_id,
                    track_id=track_id,
                    sec_uid=real_uid,
                    creator_hash=sec_uid_hash,
                    nickname=nickname,
                    enabled=True,
                    is_placeholder=False,
                    notes="由历史采集作品自动导入",
                )
            )
            real_uid_taken.add(real_uid)
            created += 1
            continue
        if sec_uid_hash in existing_hashes:
            continue
        if track_id is None:
            skipped += 1
            continue
        session.add(
            DouyinCreator(
                owner_id=owner_id,
                track_id=track_id,
                sec_uid=sec_uid_hash,
                creator_hash=sec_uid_hash,
                nickname=nickname,
                enabled=True,
                is_placeholder=True,
                notes="由历史采集作品自动导入，待补全主页链接",
            )
        )
        created += 1
    session.flush()
    session.commit()
    return DouyinAwemeSyncResult(
        total_count=len(best),
        created_count=created,
        existing_count=len(best) - created - skipped,
    )


def sync_task_creators_in_session(
    session: Session,
    *,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    sec_uids: list[str],
    track_id: uuid.UUID | None = None,
    move_existing: bool = True,
    source: DouyinKeywordSyncSource = DouyinKeywordSyncSource.automatic,
) -> tuple[int, int]:
    """在给定会话中同步任务达人：创建/复用达人并建立任务绑定。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        task_id: 采集任务 ID。
        owner_id: 归属用户 ID。
        sec_uids: 达人 sec_user_id/主页链接列表；全部为空时直接返回 (0, 0)。
        track_id: 目标赛道 ID；None 时取任务自身的赛道。
        move_existing: 已存在的达人是否允许移动到目标赛道。
        source: 绑定来源标识，写入关联记录。

    返回：
        二元组 (新建达人数, 新建绑定数)。

    异常：
        CreatorValidationError: 任务不存在或不属于该用户。
    """
    if not sec_uids:
        return 0, 0
    if track_id is None:
        task = session.get(CrawlTask, task_id)
        if task is None or task.owner_id != owner_id:
            raise CreatorValidationError("抖音任务不存在或无权访问")
        track_id = task.track_id
    creators, created, _ = create_creators(
        session,
        owner_id=owner_id,
        creators=sec_uids,
        track_id=track_id,
        move_existing=move_existing,
    )
    existing_ids = set(
        session.exec(
            select(DouyinCreatorTaskLink.creator_id).where(
                DouyinCreatorTaskLink.task_id == task_id,
                col(DouyinCreatorTaskLink.creator_id).in_(
                    [item.id for item in creators]
                ),
            )
        ).all()
    )
    bound = 0
    for creator in creators:
        if creator.id in existing_ids:
            continue
        session.add(
            DouyinCreatorTaskLink(
                creator_id=creator.id,
                task_id=task_id,
                source=source.value,
            )
        )
        bound += 1
    session.flush()
    return created, bound


def task_creators(task: CrawlTask) -> list[str]:
    """从任务请求快照（request_json）中解析出达人 sec_uid 列表，解析失败返回空列表。"""
    try:
        request = json.loads(task.request_json)
    except json.JSONDecodeError:
        return []
    values = request.get("creator_ids") if isinstance(request, dict) else None
    return [str(item) for item in values] if isinstance(values, list) else []


def creator_tasks(session: Session, *, creator_id: uuid.UUID) -> list[CrawlTask]:
    """查询达人关联的全部任务（按创建时间倒序，仅含与达人同归属用户的任务）。"""
    return list(
        session.exec(
            select(CrawlTask)
            .join(
                DouyinCreatorTaskLink,
                col(DouyinCreatorTaskLink.task_id) == col(CrawlTask.id),
            )
            .join(
                DouyinCreator,
                col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
            )
            .where(
                DouyinCreatorTaskLink.creator_id == creator_id,
                CrawlTask.owner_id == DouyinCreator.owner_id,
            )
            .order_by(col(CrawlTask.created_at).desc())
        ).all()
    )


def sync_task(
    session: Session,
    *,
    task: CrawlTask,
    source: DouyinKeywordSyncSource,
) -> tuple[int, int, int]:
    """同步单个任务的达人（不移动已存在达人的赛道归属）。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        task: 采集任务实体；无达人目标时直接返回 (0, 0, 0)。
        source: 绑定来源标识。

    返回：
        三元组 (有效达人数, 新建达人数, 新建绑定数)。
    """
    values = task_creators(task)
    if not values:
        return 0, 0, 0
    created, bound = sync_task_creators_in_session(
        session,
        task_id=task.id,
        owner_id=task.owner_id,
        sec_uids=values,
        source=source,
        move_existing=False,
    )
    return len(parse_creator_targets(values)), created, bound


def sync_history(session: Session, *, owner_id: uuid.UUID) -> tuple[int, int, int, int]:
    """回填同步用户全部历史达人任务（来源标记为 history）。

    参数：
        session: 数据库会话（本函数只 flush，不 commit）。
        owner_id: 归属用户 ID。

    返回：
        四元组 (同步的任务数, 涉及的达人数, 新建达人数, 新建绑定数)。
    """
    tasks = session.exec(
        select(CrawlTask).where(
            CrawlTask.owner_id == owner_id,
            CrawlTask.crawl_type == DouyinCrawlType.creator.value,
        )
    ).all()
    creator_count = 0
    created_count = 0
    binding_count = 0
    synced_tasks = 0
    for task in tasks:
        count, created, bound = sync_task(
            session, task=task, source=DouyinKeywordSyncSource.history
        )
        if count:
            synced_tasks += 1
            creator_count += count
            created_count += created
            binding_count += bound
    return synced_tasks, creator_count, created_count, binding_count


def _status_for(tasks: list[CrawlTask]) -> DouyinCreatorStatus:
    """由关联任务状态集合推导达人状态：有进行中则 active，有成功则 crawled，有失败则 failed，否则 unprocessed。"""
    statuses = {task.status for task in tasks}
    if statuses & ACTIVE_TASK_STATUSES:
        return DouyinCreatorStatus.active
    if CrawlTaskStatus.succeeded.value in statuses:
        return DouyinCreatorStatus.crawled
    if statuses & FAILED_TASK_STATUSES:
        return DouyinCreatorStatus.failed
    return DouyinCreatorStatus.unprocessed


def build_creator_public_rows(
    session: Session,
    *,
    owner_id: uuid.UUID,
    search: str | None = None,
    track_id: uuid.UUID | None = None,
) -> list[DouyinCreatorPublic]:
    """构建达人公开模型列表，聚合赛道信息与任务/作品统计。

    绑定任务与作品统计跟随达人当前赛道归属；任务自身仍保留创建时赛道，
    用于审计。作品数按达人 creator_hash 匹配作品的脱敏 sec_uid 汇总
    （达人 creator_hash 与 douyin_aweme.sec_uid 同为
    sec_user_id 的 SHA-256 前 16 位）。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID，仅返回其名下的达人。
        search: 模糊搜索词（匹配昵称、sec_uid 与备注），None 表示不过滤。
        track_id: 限定赛道 ID，None 表示不过滤。

    返回：
        达人公开模型列表（未排序，排序由调用方负责）。
    """
    statement = select(DouyinCreator).where(DouyinCreator.owner_id == owner_id)
    if track_id is not None:
        statement = statement.where(DouyinCreator.track_id == track_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            col(DouyinCreator.nickname).ilike(term)
            | col(DouyinCreator.sec_uid).ilike(term)
            | col(DouyinCreator.notes).ilike(term)
        )
    creators = session.exec(statement).all()
    if not creators:
        return []
    creator_ids = [item.id for item in creators]
    tracks = {
        item.id: item
        for item in session.exec(
            select(DouyinTrack).where(
                col(DouyinTrack.id).in_({item.track_id for item in creators})
            )
        ).all()
    }
    linked_rows = session.exec(
        select(DouyinCreatorTaskLink, CrawlTask)
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinCreatorTaskLink.task_id))
        .join(
            DouyinCreator,
            col(DouyinCreator.id) == col(DouyinCreatorTaskLink.creator_id),
        )
        .where(
            col(DouyinCreatorTaskLink.creator_id).in_(creator_ids),
            CrawlTask.owner_id == DouyinCreator.owner_id,
        )
    ).all()
    tasks_by_creator: dict[uuid.UUID, list[CrawlTask]] = defaultdict(list)
    for link, task in linked_rows:
        tasks_by_creator[link.creator_id].append(task)

    work_counts: dict[str, int] = defaultdict(int)
    for sec_uid, count in session.exec(
        select(
            DouyinAweme.sec_uid,
            func.count(col(DouyinAweme.id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinAweme.task_id))
        .where(
            CrawlTask.owner_id == owner_id,
            col(DouyinAweme.sec_uid) != "",
        )
        .group_by(col(DouyinAweme.sec_uid))
    ).all():
        work_counts[sec_uid] += int(count)

    output: list[DouyinCreatorPublic] = []
    for creator in creators:
        track = tracks[creator.track_id]
        tasks = tasks_by_creator.get(creator.id, [])
        ordered = sorted(tasks, key=lambda item: item.created_at, reverse=True)
        last_task = ordered[0] if ordered else None
        completed_dates = [
            task.finished_at or task.created_at
            for task in tasks
            if task.status
            in {
                CrawlTaskStatus.succeeded.value,
                *FAILED_TASK_STATUSES,
            }
        ]
        output.append(
            DouyinCreatorPublic(
                id=creator.id,
                track_id=track.id,
                track_name=track.name,
                track_is_default=track.is_default,
                sec_uid=creator.sec_uid,
                creator_hash=creator.creator_hash,
                nickname=creator.nickname,
                enabled=creator.enabled,
                is_placeholder=creator.is_placeholder,
                notes=creator.notes,
                status=_status_for(tasks),
                task_count=len(tasks),
                active_task_count=sum(
                    task.status in ACTIVE_TASK_STATUSES for task in tasks
                ),
                success_task_count=sum(
                    task.status == CrawlTaskStatus.succeeded.value for task in tasks
                ),
                failed_task_count=sum(
                    task.status in FAILED_TASK_STATUSES for task in tasks
                ),
                aweme_count=work_counts.get(creator.creator_hash, 0),
                last_task_id=last_task.id if last_task else None,
                last_task_status=(
                    CrawlTaskStatus(last_task.status) if last_task else None
                ),
                last_crawled_at=max(completed_dates) if completed_dates else None,
                created_at=creator.created_at,
                updated_at=creator.updated_at,
            )
        )
    return output


def update_creator(
    session: Session,
    *,
    item: DouyinCreator,
    nickname: str | None,
    enabled: bool | None,
    notes: str | None,
) -> DouyinCreator:
    """就地更新达人的昵称、启用状态与备注（本函数只 flush，不 commit）。

    参数：
        session: 数据库会话。
        item: 待更新的达人实体。
        nickname: 新昵称，None 表示不修改。
        enabled: 新启用状态，None 表示不修改。
        notes: 新备注，None 表示不修改。

    返回：
        更新后的达人实体。
    """
    if nickname is not None:
        item.nickname = nickname.strip()
    if enabled is not None:
        item.enabled = enabled
    if notes is not None:
        item.notes = notes.strip()
    session.add(item)
    return item


def edit_creator_record(
    session: Session,
    *,
    creator_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
    nickname: str | None,
    track_id: uuid.UUID | None,
    enabled: bool | None,
    notes: str | None,
    sec_uid: str | None = None,
) -> DouyinCreatorPublic:
    """编辑单条达人（可调整赛道归属、昵称、启用状态、备注、补全主页）并提交事务。

    参数：
        session: 数据库会话（本函数内部 commit）。
        creator_id: 达人 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。
        nickname: 新昵称，None 表示不修改。
        track_id: 目标赛道 ID；与当前赛道相同时忽略，None 表示不调整。
        enabled: 新启用状态，None 表示不修改。
        notes: 新备注，None 表示不修改。
        sec_uid: 补全用的主页 sec_user_id/链接，仅对待补全占位达人有效；
            校验脱敏哈希与历史采集数据一致后达人转正，None 表示不补全。

    返回：
        更新后的达人公开模型（含统计汇总）。

    异常：
        CreatorNotFoundError: 达人不存在。
        CreatorPermissionDeniedError: 达人属于其他用户且非超管。
        CreatorValidationError: 目标赛道非法、达人非待补全状态、
            补全链接解析失败或与历史采集数据不匹配。
        CreatorConflictError: 补全的主页已被其他达人占用。
    """
    item = get_creator_for_actor(
        session,
        creator_id=creator_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    if track_id is not None and track_id != item.track_id:
        from crawler.business.douyin.tracks.bindings import resolve_track

        try:
            track = resolve_track(
                session,
                owner_id=item.owner_id,
                track_id=track_id,
            )
        except ValueError as exc:
            raise CreatorValidationError(str(exc)) from exc
        item.track_id = track.id
        session.add(item)
    if sec_uid is not None:
        if not item.is_placeholder:
            raise CreatorValidationError("该达人不是待补全状态")
        real_uid = parse_creator_targets([sec_uid])[0]
        if anonymize_user_id(real_uid) != item.creator_hash:
            raise CreatorValidationError(
                "补全的主页与历史采集数据不匹配，请确认是同一达人"
            )
        conflict = session.exec(
            select(DouyinCreator).where(
                DouyinCreator.owner_id == item.owner_id,
                DouyinCreator.sec_uid == real_uid,
            )
        ).first()
        if conflict is not None and conflict.id != item.id:
            raise CreatorConflictError("该主页已存在其他达人")
        item.sec_uid = real_uid
        item.is_placeholder = False
        session.add(item)
    item = update_creator(
        session,
        item=item,
        nickname=nickname,
        enabled=enabled,
        notes=notes,
    )
    owner_id = item.owner_id
    session.commit()
    return next(
        row
        for row in build_creator_public_rows(session, owner_id=owner_id)
        if row.id == creator_id
    )


def delete_creator_record(
    session: Session,
    *,
    creator_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> None:
    """删除单条达人并提交事务（关联绑定随外键级联删除）。

    参数：
        session: 数据库会话（本函数内部 commit）。
        creator_id: 达人 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    异常：
        CreatorNotFoundError: 达人不存在。
        CreatorPermissionDeniedError: 达人属于其他用户且非超管。
    """
    session.delete(
        get_creator_for_actor(
            session,
            creator_id=creator_id,
            actor_id=actor_id,
            is_superuser=is_superuser,
        )
    )
    session.commit()


def delete_creator_batch(
    session: Session,
    *,
    owner_id: uuid.UUID,
    creator_ids: list[uuid.UUID],
) -> int:
    """批量删除当前用户名下的达人并提交事务。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID，仅删除其名下的达人。
        creator_ids: 待删除的达人 ID 列表。

    返回：
        实际删除的达人数量（不属于该用户的 ID 被静默忽略）。
    """
    rows = session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            col(DouyinCreator.id).in_(creator_ids),
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return len(rows)


def sync_creator_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    is_superuser: bool,
) -> DouyinCreatorSyncResult:
    """手动同步单个任务的达人并提交事务（来源标记为 manual）。

    参数：
        session: 数据库会话（本函数内部 commit）。
        task_id: 采集任务 ID。
        actor_id: 当前操作用户 ID。
        is_superuser: 是否为超管。

    返回：
        同步结果统计。

    异常：
        CreatorNotFoundError: 任务不存在。
        CreatorPermissionDeniedError: 任务属于其他用户且非超管。
        CreatorValidationError: 任务没有可同步的达人目标。
    """
    task = get_task_for_actor(
        session,
        task_id=task_id,
        actor_id=actor_id,
        is_superuser=is_superuser,
    )
    creator_count, created, bound = sync_task(
        session,
        task=task,
        source=DouyinKeywordSyncSource.manual,
    )
    if not creator_count:
        raise CreatorValidationError("该任务没有可同步的达人")
    session.commit()
    return DouyinCreatorSyncResult(
        task_count=1,
        creator_count=creator_count,
        created_count=created,
        binding_count=bound,
    )


def sync_creator_history(
    session: Session,
    *,
    owner_id: uuid.UUID,
) -> DouyinCreatorSyncResult:
    """回填同步当前用户全部历史达人任务并提交事务。

    参数：
        session: 数据库会话（本函数内部 commit）。
        owner_id: 归属用户 ID。

    返回：
        同步结果统计（任务数、达人数、新建数、绑定数）。
    """
    task_count, creator_count, created, bound = sync_history(
        session,
        owner_id=owner_id,
    )
    session.commit()
    return DouyinCreatorSyncResult(
        task_count=task_count,
        creator_count=creator_count,
        created_count=created,
        binding_count=bound,
    )


async def create_creator_crawl_tasks(
    session: Session,
    *,
    owner_id: uuid.UUID,
    request: DouyinCreatorBatchTaskRequest,
) -> DouyinCreatorTaskBatchResult:
    """基于选中达人批量创建达人采集任务（每达人一个独立任务）。

    达人任务固定独立模式：每个达人单独创建一个任务，一次最多 20 个。

    参数：
        session: 数据库会话。
        owner_id: 归属用户 ID。
        request: 批量建任务请求体（达人 ID 列表、模式与采集参数）。

    返回：
        新建任务的公开模型列表与数量。

    异常：
        CreatorNotFoundError: 部分达人不存在或不属于该用户。
        CreatorConflictError: 选中的达人包含已停用项目。
        CreatorValidationError: 跨赛道混合选择、数量超限或任务创建参数非法。
    """
    from crawler.business.douyin.tasks.query_service import build_tasks_public
    from crawler.business.douyin.tasks.service import task_manager

    unique_ids = list(dict.fromkeys(request.creator_ids))
    creators = session.exec(
        select(DouyinCreator).where(
            DouyinCreator.owner_id == owner_id,
            col(DouyinCreator.id).in_(unique_ids),
        )
    ).all()
    by_id = {item.id: item for item in creators}
    if len(by_id) != len(unique_ids):
        raise CreatorNotFoundError("部分达人不存在或无权访问")
    if any(not by_id[item_id].enabled for item_id in unique_ids):
        raise CreatorConflictError("选中的达人包含已停用项目")
    if any(by_id[item_id].is_placeholder for item_id in unique_ids):
        raise CreatorConflictError("选中的达人包含待补全项目，请先补全主页链接")
    from crawler.business.douyin.tracks.bindings import resolve_track

    selected_track_ids = {by_id[item_id].track_id for item_id in unique_ids}
    if request.track_id is None:
        if len(selected_track_ids) != 1:
            raise CreatorValidationError(
                "不能跨赛道混合创建任务，请先选择同一赛道的达人"
            )
        resolved_track_id = next(iter(selected_track_ids))
    else:
        resolved_track_id = request.track_id
        if selected_track_ids != {resolved_track_id}:
            raise CreatorValidationError("选中的达人不全部属于指定赛道")
    track = resolve_track(
        session,
        owner_id=owner_id,
        track_id=resolved_track_id,
    )
    if len(unique_ids) > 20:
        raise CreatorValidationError("独立任务模式一次最多创建 20 个任务")

    tasks: list[CrawlTask] = []
    for creator_id in unique_ids:
        creator = by_id[creator_id]
        task_request = CrawlTaskCreate(
            track_id=track.id,
            crawl_type=DouyinCrawlType.creator,
            login_type=request.login_type,
            browser_mode=request.browser_mode,
            cookies=request.cookies,
            creator_ids=[creator.sec_uid],
            start_page=request.start_page,
            max_awemes=request.max_awemes,
            fetch_comments=request.fetch_comments,
            fetch_sub_comments=request.fetch_sub_comments,
            max_comments_per_aweme=request.max_comments_per_aweme,
            concurrency=request.concurrency,
            request_delay_level=request.request_delay_level,
            request_interval_seconds=request.request_interval_seconds,
            task_interval_seconds=request.task_interval_seconds,
            publish_time=request.publish_time,
            media_processing_mode=request.media_processing_mode,
            media_storage=request.media_storage,
            download_media=request.download_media,
            translate_subtitles=request.translate_subtitles,
            transcription_language=request.transcription_language,
            account_id=request.account_id,
            account_ids=request.account_ids,
            account_pool_id=request.account_pool_id,
            account_strategy=request.account_strategy,
        )
        try:
            task = await task_manager.create(owner_id=owner_id, request=task_request)
        except ValueError as exc:
            raise CreatorValidationError(str(exc)) from exc
        if task.track_id != track.id:
            raise CreatorValidationError("任务创建后的赛道归属不一致")
        tasks.append(task)
    return DouyinCreatorTaskBatchResult(
        data=build_tasks_public(session, tasks=tasks),
        count=len(tasks),
    )


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "FAILED_TASK_STATUSES",
    "CreatorServiceError",
    "CreatorNotFoundError",
    "CreatorPermissionDeniedError",
    "CreatorValidationError",
    "CreatorConflictError",
    "get_creator_for_actor",
    "get_task_for_actor",
    "parse_creator_targets",
    "create_creators",
    "create_creator_batch",
    "import_aweme_creators",
    "sync_task_creators_in_session",
    "task_creators",
    "creator_tasks",
    "build_creator_public_rows",
    "edit_creator_record",
    "delete_creator_record",
    "delete_creator_batch",
    "sync_creator_task",
    "sync_creator_history",
    "create_creator_crawl_tasks",
]
