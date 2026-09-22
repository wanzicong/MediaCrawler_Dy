"""内容分类的读写用例：两级分类树维护 + 视频/达人归类 + 筛选解析。"""

from __future__ import annotations

import unicodedata
import uuid
from collections import defaultdict

from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.categories.models import (
    DouyinCategoriesPublic,
    DouyinCategory,
    DouyinCategoryAssignResult,
    DouyinCategoryCreate,
    DouyinCategoryPublic,
    DouyinCreatorCategory,
    DouyinVideoCategory,
)
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.errors import (
    ConflictError,
    InvalidRequestError,
    ResourceNotFoundError,
)
from sqlmodel import Session, col, func, select

MAX_LEVEL = 2


def normalize_name(value: str) -> str:
    """分类名归一化：NFKC + 去空白 + casefold，用于同级去重。"""
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _require_category(
    session: Session, *, owner_id: uuid.UUID, category_id: uuid.UUID
) -> DouyinCategory:
    """取本人名下的分类，不存在或非本人时抛错。"""
    item = session.get(DouyinCategory, category_id)
    if item is None or item.owner_id != owner_id:
        raise ResourceNotFoundError("分类不存在或无权访问")
    return item


def _require_parent(
    session: Session, *, owner_id: uuid.UUID, parent_id: uuid.UUID | None
) -> DouyinCategory | None:
    """校验父分类：必须存在、属于本人，且本身是一级分类（保证最多两级）。"""
    if parent_id is None:
        return None
    parent = _require_category(session, owner_id=owner_id, category_id=parent_id)
    if parent.parent_id is not None:
        raise InvalidRequestError("分类最多两级，子分类下不能再建分类")
    return parent


def list_categories(session: Session, *, owner_id: uuid.UUID) -> DouyinCategoriesPublic:
    """列出当前用户的全部分类（扁平，含直接归类的视频/达人数）。"""
    rows = session.exec(
        select(DouyinCategory)
        .where(DouyinCategory.owner_id == owner_id)
        .order_by(
            col(DouyinCategory.sort_order).asc(),
            col(DouyinCategory.created_at).asc(),
        )
    ).all()
    video_counts = dict(
        session.exec(
            select(
                DouyinVideoCategory.category_id,
                func.count(col(DouyinVideoCategory.id)),
            )
            .where(DouyinVideoCategory.owner_id == owner_id)
            .group_by(col(DouyinVideoCategory.category_id))
        ).all()
    )
    creator_counts = dict(
        session.exec(
            select(
                DouyinCreatorCategory.category_id,
                func.count(col(DouyinCreatorCategory.id)),
            )
            .join(
                DouyinCreator,
                col(DouyinCreator.id) == col(DouyinCreatorCategory.creator_id),
            )
            .where(DouyinCreator.owner_id == owner_id)
            .group_by(col(DouyinCreatorCategory.category_id))
        ).all()
    )
    data = [
        DouyinCategoryPublic(
            id=item.id,
            parent_id=item.parent_id,
            name=item.name,
            description=item.description,
            sort_order=item.sort_order,
            level=2 if item.parent_id else 1,
            video_count=int(video_counts.get(item.id, 0)),
            creator_count=int(creator_counts.get(item.id, 0)),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in rows
    ]
    return DouyinCategoriesPublic(data=data, count=len(data))


def create_category(
    session: Session, *, owner_id: uuid.UUID, request: DouyinCategoryCreate
) -> DouyinCategoryPublic:
    """新建分类；同级同名冲突时返回 409。"""
    parent = _require_parent(session, owner_id=owner_id, parent_id=request.parent_id)
    normalized = normalize_name(request.name)
    if not normalized:
        raise InvalidRequestError("分类名称不能为空")
    existing = session.exec(
        select(DouyinCategory).where(
            DouyinCategory.owner_id == owner_id,
            DouyinCategory.parent_id == (parent.id if parent else None),
            DouyinCategory.normalized_name == normalized,
        )
    ).first()
    if existing is not None:
        raise ConflictError("同级下已存在同名分类")
    item = DouyinCategory(
        owner_id=owner_id,
        parent_id=parent.id if parent else None,
        name=request.name.strip(),
        normalized_name=normalized,
        description=request.description,
        sort_order=request.sort_order,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _public_one(session, owner_id=owner_id, category_id=item.id)


def update_category(
    session: Session,
    *,
    owner_id: uuid.UUID,
    category_id: uuid.UUID,
    name: str | None,
    parent_id: uuid.UUID | None,
    description: str | None,
    sort_order: int | None,
) -> DouyinCategoryPublic:
    """重命名 / 调整层级与排序。"""
    item = _require_category(session, owner_id=owner_id, category_id=category_id)
    if parent_id is not None:
        if parent_id == item.id:
            raise InvalidRequestError("分类不能作为自己的父分类")
        parent = _require_parent(session, owner_id=owner_id, parent_id=parent_id)
        # 大类下已挂子类时不允许再变成子类，否则会出现三级
        has_children = session.exec(
            select(func.count())
            .select_from(DouyinCategory)
            .where(DouyinCategory.parent_id == item.id)
        ).one()
        if has_children and parent is not None:
            raise InvalidRequestError("该分类下已有子分类，不能再移动到其它分类下")
        item.parent_id = parent.id if parent else None
    if name is not None:
        normalized = normalize_name(name)
        if not normalized:
            raise InvalidRequestError("分类名称不能为空")
        duplicated = session.exec(
            select(DouyinCategory).where(
                DouyinCategory.owner_id == owner_id,
                DouyinCategory.parent_id == item.parent_id,
                DouyinCategory.normalized_name == normalized,
                DouyinCategory.id != item.id,
            )
        ).first()
        if duplicated is not None:
            raise ConflictError("同级下已存在同名分类")
        item.name = name.strip()
        item.normalized_name = normalized
    if description is not None:
        item.description = description
    if sort_order is not None:
        item.sort_order = sort_order
    item.updated_at = get_datetime_utc()
    session.add(item)
    session.commit()
    return _public_one(session, owner_id=owner_id, category_id=item.id)


def delete_category(
    session: Session, *, owner_id: uuid.UUID, category_id: uuid.UUID
) -> None:
    """删除分类：其子分类与归类关系一并删除（外键级联），视频/达人本身不受影响。"""
    item = _require_category(session, owner_id=owner_id, category_id=category_id)
    session.delete(item)
    session.commit()


def assign_items(
    session: Session,
    *,
    owner_id: uuid.UUID,
    category_id: uuid.UUID,
    aweme_ids: list[str],
    creator_ids: list[uuid.UUID],
    attach: bool,
) -> DouyinCategoryAssignResult:
    """把视频/达人加入或移出某个分类。"""
    _require_category(session, owner_id=owner_id, category_id=category_id)
    video_count = 0
    if aweme_ids:
        unique_ids = {value for value in aweme_ids if value}
        if attach:
            existing = {
                row.aweme_id
                for row in session.exec(
                    select(DouyinVideoCategory).where(
                        DouyinVideoCategory.owner_id == owner_id,
                        DouyinVideoCategory.category_id == category_id,
                        col(DouyinVideoCategory.aweme_id).in_(unique_ids),
                    )
                ).all()
            }
            for aweme_id in unique_ids - existing:
                session.add(
                    DouyinVideoCategory(
                        owner_id=owner_id,
                        aweme_id=aweme_id,
                        category_id=category_id,
                    )
                )
                video_count += 1
        else:
            video_rows = session.exec(
                select(DouyinVideoCategory).where(
                    DouyinVideoCategory.owner_id == owner_id,
                    DouyinVideoCategory.category_id == category_id,
                    col(DouyinVideoCategory.aweme_id).in_(unique_ids),
                )
            ).all()
            for video_row in video_rows:
                session.delete(video_row)
                video_count += 1
    creator_count = 0
    if creator_ids:
        owned: set[uuid.UUID] = {
            item.id
            for item in session.exec(
                select(DouyinCreator).where(
                    DouyinCreator.owner_id == owner_id,
                    col(DouyinCreator.id).in_(set(creator_ids)),
                )
            ).all()
        }
        if attach:
            existing_creators: set[uuid.UUID] = set()
            for link in session.exec(
                select(DouyinCreatorCategory).where(
                    DouyinCreatorCategory.category_id == category_id,
                    col(DouyinCreatorCategory.creator_id).in_(owned),
                )
            ).all():
                existing_creators.add(link.creator_id)
            for creator_id in owned - existing_creators:
                session.add(
                    DouyinCreatorCategory(
                        creator_id=creator_id, category_id=category_id
                    )
                )
                creator_count += 1
        else:
            creator_rows = session.exec(
                select(DouyinCreatorCategory).where(
                    DouyinCreatorCategory.category_id == category_id,
                    col(DouyinCreatorCategory.creator_id).in_(owned),
                )
            ).all()
            for creator_row in creator_rows:
                session.delete(creator_row)
                creator_count += 1
    session.commit()
    return DouyinCategoryAssignResult(
        category_id=category_id,
        video_count=video_count,
        creator_count=creator_count,
    )


def category_scope_ids(
    session: Session, *, owner_id: uuid.UUID, category_id: uuid.UUID
) -> list[uuid.UUID]:
    """选中一个分类时要包含的分类 id 集合：大类带出它的全部子类。"""
    _require_category(session, owner_id=owner_id, category_id=category_id)
    children = session.exec(
        select(DouyinCategory.id).where(
            DouyinCategory.owner_id == owner_id,
            DouyinCategory.parent_id == category_id,
        )
    ).all()
    return [category_id, *list(children)]


def videos_in_categories(
    session: Session, *, owner_id: uuid.UUID, category_ids: list[uuid.UUID]
) -> list[str]:
    """分类（含子类）下已归类的平台作品号。"""
    if not category_ids:
        return []
    return [
        row
        for row in session.exec(
            select(DouyinVideoCategory.aweme_id).where(
                DouyinVideoCategory.owner_id == owner_id,
                col(DouyinVideoCategory.category_id).in_(category_ids),
            )
        ).all()
        if row
    ]


def creators_in_categories(
    session: Session, *, owner_id: uuid.UUID, category_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """分类（含子类）下已归类的达人 id。"""
    if not category_ids:
        return []
    return [
        row
        for row in session.exec(
            select(DouyinCreatorCategory.creator_id)
            .join(
                DouyinCreator,
                col(DouyinCreator.id) == col(DouyinCreatorCategory.creator_id),
            )
            .where(
                DouyinCreator.owner_id == owner_id,
                col(DouyinCreatorCategory.category_id).in_(category_ids),
            )
        ).all()
        if row
    ]


def categories_of_videos(
    session: Session, *, owner_id: uuid.UUID, aweme_ids: list[str]
) -> dict[str, list[uuid.UUID]]:
    """批量查询视频所属分类，用于列表展示与批量操作回填。"""
    if not aweme_ids:
        return {}
    rows = session.exec(
        select(DouyinVideoCategory.aweme_id, DouyinVideoCategory.category_id).where(
            DouyinVideoCategory.owner_id == owner_id,
            col(DouyinVideoCategory.aweme_id).in_(set(aweme_ids)),
        )
    ).all()
    result: dict[str, list[uuid.UUID]] = defaultdict(list)
    for aweme_id, category_id in rows:
        result[aweme_id].append(category_id)
    return dict(result)


def _public_one(
    session: Session, *, owner_id: uuid.UUID, category_id: uuid.UUID
) -> DouyinCategoryPublic:
    """取单个分类的对外模型。"""
    for row in list_categories(session, owner_id=owner_id).data:
        if row.id == category_id:
            return row
    raise ResourceNotFoundError("分类不存在或无权访问")


__all__ = [
    "MAX_LEVEL",
    "assign_items",
    "categories_of_videos",
    "category_scope_ids",
    "create_category",
    "creators_in_categories",
    "delete_category",
    "list_categories",
    "normalize_name",
    "update_category",
    "videos_in_categories",
]
