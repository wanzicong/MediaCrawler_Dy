"""测试通用工具：随机字符串/邮箱生成与超级用户认证请求头获取。"""

import random
import string

from crawler.bootstrap.settings import settings
from fastapi.testclient import TestClient


def random_lower_string() -> str:
    """生成 32 位随机小写字母字符串。"""
    return "".join(random.choices(string.ascii_lowercase, k=32))


def random_email() -> str:
    """生成随机邮箱地址。"""
    return f"{random_lower_string()}@{random_lower_string()}.com"


def get_superuser_token_headers(client: TestClient) -> dict[str, str]:
    """使用配置的初始超级用户登录并返回 Bearer 认证请求头。"""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers
