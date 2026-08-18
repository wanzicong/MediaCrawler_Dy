"""身份域初始化用例：创建系统的初始管理员账号。"""

from crawler.bootstrap.settings import settings
from crawler.business.identity import service
from crawler.business.identity.models import User, UserCreate
from sqlmodel import Session, select


def init_db(session: Session) -> None:
    """当配置中的初始超级管理员不存在时创建之。

    参数：
        session: 数据库会话。
    """

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if user is None:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        service.create_user(session=session, user_create=user_in)


__all__ = ["init_db"]
