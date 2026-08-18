"""私有（内部运维）路由的集成测试。"""

from crawler.bootstrap.settings import settings
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def test_create_user(client: TestClient, db: Session) -> None:
    """验证私有路由可创建用户，且数据正确写入数据库。"""
    r = client.post(
        f"{settings.API_V1_STR}/private/users/",
        json={
            "email": "pollo@listo.com",
            "password": "password123",
            "full_name": "Pollo Listo",
        },
    )

    assert r.status_code == 200

    data = r.json()

    user = db.exec(select(User).where(User.id == data["id"])).first()

    assert user
    assert user.email == "pollo@listo.com"
    assert user.full_name == "Pollo Listo"
