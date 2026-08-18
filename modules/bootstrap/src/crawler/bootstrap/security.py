"""认证与密码哈希原语：JWT 访问令牌签发及口令哈希校验。"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from crawler.bootstrap.settings import settings
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

# 密码哈希器：新口令使用 Argon2 哈希，同时兼容校验历史 Bcrypt 哈希
password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"  # JWT 签名算法


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    """签发一个带过期时间的 JWT 访问令牌。

    参数：
        subject: 令牌主体（通常为用户 ID），会以字符串形式写入 sub 声明。
        expires_delta: 自签发时刻起的有效期时长。

    返回：
        使用 HS256 与全局密钥签名的 JWT 字符串。
    """
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """校验明文口令与已存储哈希是否匹配。

    参数：
        plain_password: 用户输入的明文口令。
        hashed_password: 数据库中存储的口令哈希。

    返回：
        (是否匹配, 可选的新哈希)；当旧哈希算法已过时，第二项为升级后的哈希。
    """
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """计算明文口令的哈希值（默认使用 Argon2）。

    参数：
        password: 明文口令。

    返回：
        可安全存储的口令哈希字符串。
    """
    return password_hash.hash(password)
