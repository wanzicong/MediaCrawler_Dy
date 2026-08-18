"""pytest 全局夹具：测试数据库会话、HTTP 客户端与认证请求头。

db 夹具在会话级初始化数据库并记录基线数据，测试结束后仅清理测试期间新增的
任务、作品与用户，保留测试前已存在的开发数据。
"""

from collections.abc import Generator

import pytest
from crawler.api.main import app
from crawler.bootstrap.database import engine
from crawler.bootstrap.settings import settings
from crawler.business.douyin.tasks.models import CrawlTask
from crawler.business.identity.bootstrap import init_db
from crawler.business.identity.models import User
from crawler.business.items.models import Item
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    """会话级夹具：初始化数据库并记录基线数据，结束时仅删除测试期间新增的数据。"""
    with Session(engine) as session:
        init_db(session)
        baseline_task_ids = set(session.exec(select(CrawlTask.id)).all())
        baseline_item_ids = set(session.exec(select(Item.id)).all())
        baseline_user_ids = set(session.exec(select(User.id)).all())
        yield session
        session.rollback()
        # 保留测试会话开始前已存在的开发数据。
        # 删除全部用户还会级联删除已持久化的抖音任务。
        session.execute(
            delete(CrawlTask).where(col(CrawlTask.id).not_in(baseline_task_ids))
        )
        session.execute(delete(Item).where(col(Item.id).not_in(baseline_item_ids)))
        session.execute(delete(User).where(col(User.id).not_in(baseline_user_ids)))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """模块级夹具：提供基于 FastAPI TestClient 的 HTTP 测试客户端。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    """模块级夹具：返回超级用户的 Bearer 认证请求头。"""
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    """模块级夹具：返回普通测试用户的 Bearer 认证请求头（用户不存在时自动创建）。"""
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
