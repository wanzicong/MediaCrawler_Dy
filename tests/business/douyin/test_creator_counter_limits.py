"""达人主页计数的容量回归测试：头部账号的获赞总数会超出 INTEGER 上限。"""

import uuid

from crawler.bootstrap.settings import settings
from crawler.business.douyin.creators.models import DouyinCreator
from crawler.business.douyin.creators.profile_sync import apply_profile_payload
from crawler.business.identity.models import User
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


def test_creator_counters_accept_values_beyond_int4(db: Session) -> None:
    """验证「获赞总数」超过 21 亿（INTEGER 上限）时仍能落库。

    背景：央视新闻这类账号的主页获赞是全部作品点赞之和（实测 13,730,728,552），
    列类型为 INTEGER 时同步会抛 NumericValueOutOfRange，整批达人一起回滚。
    """
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    creator = DouyinCreator(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        sec_uid=f"MS4wLjABAAAA-{suffix}",
        creator_hash=f"hash-{suffix}",
        nickname="待同步",
    )
    db.add(creator)
    db.commit()

    # 模拟本人资料接口返回的头部账号数据
    apply_profile_payload(
        creator,
        {
            "user": {
                "nickname": "央视新闻",
                "follower_count": 187_167_730,
                "total_favorited": 13_730_728_552,
                "aweme_count": 18_430,
                "unique_id": "cctvnews",
            }
        },
    )
    db.add(creator)
    db.commit()
    db.expire_all()

    stored = db.exec(select(DouyinCreator).where(DouyinCreator.id == creator.id)).one()
    assert stored.follower_count == 187_167_730
    assert stored.total_favorited == 13_730_728_552
    assert stored.aweme_total_count == 18_430

    db.delete(stored)
    db.commit()
