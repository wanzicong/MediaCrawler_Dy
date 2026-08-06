from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import CrawlTask, Item, User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        baseline_task_ids = set(session.exec(select(CrawlTask.id)).all())
        baseline_item_ids = set(session.exec(select(Item.id)).all())
        baseline_user_ids = set(session.exec(select(User.id)).all())
        yield session
        session.rollback()
        # Preserve development data that existed before the test session.
        # Deleting every user also cascades into persisted Douyin tasks.
        session.execute(
            delete(CrawlTask).where(
                col(CrawlTask.id).not_in(baseline_task_ids)
            )
        )
        session.execute(
            delete(Item).where(col(Item.id).not_in(baseline_item_ids))
        )
        session.execute(
            delete(User).where(col(User.id).not_in(baseline_user_ids))
        )
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
