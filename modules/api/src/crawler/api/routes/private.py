"""内部私有路由：仅 local 环境挂载，供开发调试直接创建用户，不做鉴权。"""

from typing import Any

from crawler.api.deps import SessionDep
from crawler.business.identity.models import UserPublic
from crawler.business.identity.service import create_private_user
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    """私有接口创建用户的请求模型。"""

    email: str  # 用户邮箱
    password: str  # 明文密码（入库前由业务层哈希）
    full_name: str  # 用户全名
    is_verified: bool = False  # 是否已验证邮箱


@router.post("/users/", response_model=UserPublic)
def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """创建新用户（本地调试专用，无需鉴权）。

    参数：
        user_in: 用户创建参数。
        session: 数据库会话依赖。

    返回：
        创建成功的用户信息。
    """

    return create_private_user(
        session=session,
        email=user_in.email,
        password=user_in.password,
        full_name=user_in.full_name,
    )
