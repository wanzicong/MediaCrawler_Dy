"""登录与密码管理路由的集成测试。

覆盖令牌签发、CORS 预检、密码找回/重置，以及历史 bcrypt 密码哈希在登录时
自动升级为 argon2 的行为。
"""

from unittest.mock import patch

from crawler.bootstrap.security import get_password_hash, verify_password
from crawler.bootstrap.settings import settings
from crawler.business.identity.mail import generate_password_reset_token
from crawler.business.identity.models import User, UserCreate
from crawler.business.identity.service import create_user
from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session

from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def test_get_access_token(client: TestClient) -> None:
    """验证正确的超级用户凭据可换取 access_token。"""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_with_username(client: TestClient, db: Session) -> None:
    """验证短用户名和短历史密码也能通过前后端共用登录接口认证。"""
    username = f"admin-{random_lower_string()[:8]}"
    password = "admin"
    user = User(
        email=random_email(),
        username=username,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_superuser=True,
    )
    db.add(user)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": username, "password": password},
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    current = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert current.status_code == 200
    assert current.json()["username"] == username

    db.delete(user)
    db.commit()


def test_login_preflight_allows_local_frontend(client: TestClient) -> None:
    """验证 CORS 预检请求放行本地前端来源（http://127.0.0.1:5173）。"""
    origin = "http://127.0.0.1:5173"
    response = client.options(
        f"{settings.API_V1_STR}/login/access-token",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    """验证错误密码登录返回 400。"""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """验证 test-token 接口可用 access_token 换取当前用户信息。"""
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """验证已注册邮箱的密码找回请求返回 200 与统一提示文案。"""
    with (
        patch("crawler.bootstrap.settings.settings.SMTP_HOST", "smtp.example.com"),
        patch("crawler.bootstrap.settings.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    """验证未注册邮箱的找回请求同样返回 200 统一提示，防止邮箱枚举攻击。"""
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    # 应返回 200 与统一提示，防止邮箱枚举攻击
    assert r.status_code == 200
    assert r.json() == {
        "message": "If that email is registered, we sent a password recovery link"
    }


def test_reset_password(client: TestClient, db: Session) -> None:
    """验证凭有效重置 token 可重置密码，且新密码哈希写入数据库。"""
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        email=email,
        full_name="Test User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    user = create_user(session=db, user_create=user_create)
    token = generate_password_reset_token(email=email)
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """验证无效重置 token 返回 400 及 Invalid token 提示。"""
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """验证使用 bcrypt 哈希的密码登录成功后，哈希会被自动升级为 argon2。"""
    email = random_email()
    password = random_lower_string()

    # 直接构造 bcrypt 哈希（模拟历史遗留密码）
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt 哈希以 $2 开头

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # 校验哈希已升级为 argon2
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # 已是 argon2，无需再次升级
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """验证使用 argon2 哈希的密码登录后，哈希保持不变。"""
    email = random_email()
    password = random_lower_string()

    # 构造 argon2 哈希（当前默认算法）
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # 创建使用 argon2 哈希的用户
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")
