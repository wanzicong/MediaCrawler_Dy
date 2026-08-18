"""用户 CRUD 的测试：覆盖用户创建、认证、状态校验、更新以及密码哈希算法升级等身份模块行为。"""

from crawler.bootstrap.security import verify_password
from crawler.business.identity import service as crud
from crawler.business.identity.models import User, UserCreate, UserUpdate
from fastapi.encoders import jsonable_encoder
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session

from tests.utils.utils import random_email, random_lower_string


def test_create_user(db: Session) -> None:
    """验证创建用户后邮箱正确且已生成 hashed_password 字段。"""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    assert user.email == email
    assert hasattr(user, "hashed_password")


def test_authenticate_user(db: Session) -> None:
    """验证使用正确邮箱与密码可以认证成功并返回对应用户。"""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    authenticated_user = crud.authenticate(session=db, email=email, password=password)
    assert authenticated_user
    assert user.email == authenticated_user.email


def test_not_authenticate_user(db: Session) -> None:
    """验证用户不存在时认证返回 None 而非抛异常。"""
    email = random_email()
    password = random_lower_string()
    user = crud.authenticate(session=db, email=email, password=password)
    assert user is None


def test_check_if_user_is_active(db: Session) -> None:
    """验证默认创建的用户处于激活状态（is_active 为 True）。"""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    assert user.is_active is True


def test_check_if_user_is_active_inactive(db: Session) -> None:
    """验证显式传入 is_active=False 创建的用户处于停用状态。"""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, is_active=False)
    user = crud.create_user(session=db, user_create=user_in)
    assert user.is_active is False


def test_check_if_user_is_superuser(db: Session) -> None:
    """验证显式传入 is_superuser=True 创建的用户具有超级管理员标记。"""
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, is_superuser=True)
    user = crud.create_user(session=db, user_create=user_in)
    assert user.is_superuser is True


def test_check_if_user_is_superuser_normal_user(db: Session) -> None:
    """验证默认创建的普通用户不具备超级管理员标记。"""
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    assert user.is_superuser is False


def test_get_user(db: Session) -> None:
    """验证按 id 从数据库读取的用户与创建时写入的数据一致。"""
    password = random_lower_string()
    username = random_email()
    user_in = UserCreate(email=username, password=password, is_superuser=True)
    user = crud.create_user(session=db, user_create=user_in)
    user_2 = db.get(User, user.id)
    assert user_2
    assert user.email == user_2.email
    assert jsonable_encoder(user) == jsonable_encoder(user_2)


def test_update_user(db: Session) -> None:
    """验证更新用户密码后，新密码哈希能通过校验且邮箱保持不变。"""
    password = random_lower_string()
    email = random_email()
    user_in = UserCreate(email=email, password=password, is_superuser=True)
    user = crud.create_user(session=db, user_create=user_in)
    new_password = random_lower_string()
    user_in_update = UserUpdate(password=new_password, is_superuser=True)
    if user.id is not None:
        crud.update_user(session=db, db_user=user, user_in=user_in_update)
    user_2 = db.get(User, user.id)
    assert user_2
    assert user.email == user_2.email
    verified, _ = verify_password(new_password, user_2.hashed_password)
    assert verified


def test_authenticate_user_with_bcrypt_upgrades_to_argon2(db: Session) -> None:
    """验证使用 bcrypt 哈希密码的老用户在登录认证成功后，密码哈希会自动升级为 argon2。"""
    email = random_email()
    password = random_lower_string()

    # 直接生成 bcrypt 哈希（模拟历史遗留密码）
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt 哈希以 $2 开头

    # 直接在数据库中创建使用 bcrypt 哈希的用户
    user = User(email=email, hashed_password=bcrypt_hash)
    db.add(user)
    db.commit()
    db.refresh(user)

    # 认证前确认哈希确为 bcrypt 格式
    assert user.hashed_password.startswith("$2")

    # 执行认证——此过程应触发哈希升级为 argon2
    authenticated_user = crud.authenticate(session=db, email=email, password=password)
    assert authenticated_user
    assert authenticated_user.email == email

    db.refresh(authenticated_user)

    # 验证哈希已被升级为 argon2
    assert authenticated_user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(
        password, authenticated_user.hashed_password
    )
    assert verified
    # 已是 argon2 哈希，不应再返回需要更新的新哈希
    assert updated_hash is None
