"""Transactional identity use cases.

The domain owns the user model; this module owns persistence orchestration.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session, col, delete, func, select

from app import utils
from app.bootstrap.settings import settings
from app.domain.identity.models import (
    TokenPayload,
    UpdatePassword,
    User,
    UserCreate,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.domain.items.models import Item
from app.framework.security import (
    ALGORITHM,
    create_access_token,
    get_password_hash,
    verify_password,
)


class IdentityServiceError(Exception):
    """Base class for expected identity use-case failures."""


class EmailAlreadyExistsError(IdentityServiceError):
    """A user already owns the requested email address."""


class UserNotFoundError(IdentityServiceError):
    """The requested user does not exist."""


class InsufficientPrivilegesError(IdentityServiceError):
    """The actor cannot access the requested user."""


class SelfDeletionForbiddenError(IdentityServiceError):
    """A superuser attempted to delete their own account."""


class IncorrectPasswordError(IdentityServiceError):
    """The supplied current password is invalid."""


class PasswordReuseError(IdentityServiceError):
    """The new password is identical to the current password."""


class InvalidCredentialsError(IdentityServiceError):
    """The supplied email/password pair is invalid."""


class InactiveUserError(IdentityServiceError):
    """The authenticated user is inactive."""


class InvalidResetTokenError(IdentityServiceError):
    """The password reset token is invalid or has no matching user."""


@dataclass(frozen=True)
class PasswordRecoveryContent:
    """Transport-neutral password recovery email content."""

    html_content: str
    subject: str


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> User:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()


def resolve_token_user(*, session: Session, token: str) -> User:
    """Resolve an active user from an access token without HTTP concerns."""

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise InvalidCredentialsError from exc
    user = session.get(User, token_data.sub)
    if user is None:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError
    return user


def create_private_user(
    *,
    session: Session,
    email: str,
    password: str,
    full_name: str,
) -> User:
    """Preserve the local-only unchecked user creation helper."""

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
    )
    session.add(user)
    session.commit()
    return user


# Argon2 hash used to equalize authentication timing for unknown users.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def list_users(
    *, session: Session, skip: int = 0, limit: int = 100
) -> UsersPublic:
    """Return users in the same newest-first order exposed by the API."""

    count = session.exec(select(func.count()).select_from(User)).one()
    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = list(session.exec(statement).all())
    return UsersPublic(data=users, count=count)


def create_managed_user(*, session: Session, user_in: UserCreate) -> User:
    """Create an administrator-managed user and send the optional welcome email."""

    if get_user_by_email(session=session, email=user_in.email) is not None:
        raise EmailAlreadyExistsError

    user = create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = utils.generate_new_account_email(
            email_to=user_in.email,
            username=user_in.email,
            password=user_in.password,
        )
        utils.send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


def update_current_user(
    *, session: Session, current_user: User, user_in: UserUpdateMe
) -> User:
    """Update the current user's profile and enforce email uniqueness."""

    if user_in.email:
        existing_user = get_user_by_email(session=session, email=user_in.email)
        if existing_user is not None and existing_user.id != current_user.id:
            raise EmailAlreadyExistsError

    current_user.sqlmodel_update(user_in.model_dump(exclude_unset=True))
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


def update_current_password(
    *, session: Session, current_user: User, body: UpdatePassword
) -> None:
    """Validate and update the current user's password."""

    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise IncorrectPasswordError
    if body.current_password == body.new_password:
        raise PasswordReuseError

    current_user.hashed_password = get_password_hash(body.new_password)
    session.add(current_user)
    session.commit()


def delete_current_user(*, session: Session, current_user: User) -> None:
    """Delete the current non-superuser account."""

    if current_user.is_superuser:
        raise SelfDeletionForbiddenError
    session.delete(current_user)
    session.commit()


def register_user(*, session: Session, user_in: UserRegister) -> User:
    """Register a user without authentication."""

    if get_user_by_email(session=session, email=user_in.email) is not None:
        raise EmailAlreadyExistsError
    return create_user(
        session=session,
        user_create=UserCreate.model_validate(user_in),
    )


def get_visible_user(
    *, session: Session, current_user: User, user_id: uuid.UUID
) -> User:
    """Return a user while preserving the existing anti-enumeration ordering."""

    user = session.get(User, user_id)
    if user == current_user:
        return current_user
    if not current_user.is_superuser:
        # This check intentionally precedes the not-found response.  It preserves
        # the existing behavior that prevents normal users enumerating user IDs.
        raise InsufficientPrivilegesError
    if user is None:
        raise UserNotFoundError
    return user


def update_managed_user(
    *,
    session: Session,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> User:
    """Update an administrator-managed user."""

    db_user = session.get(User, user_id)
    if db_user is None:
        raise UserNotFoundError
    if user_in.email:
        existing_user = get_user_by_email(session=session, email=user_in.email)
        if existing_user is not None and existing_user.id != user_id:
            raise EmailAlreadyExistsError
    return update_user(session=session, db_user=db_user, user_in=user_in)


def delete_managed_user(
    *, session: Session, current_user: User, user_id: uuid.UUID
) -> None:
    """Delete a user and their legacy items in one transaction."""

    user = session.get(User, user_id)
    if user is None:
        raise UserNotFoundError
    if user == current_user:
        raise SelfDeletionForbiddenError

    session.exec(delete(Item).where(col(Item.owner_id) == user_id))
    session.delete(user)
    session.commit()


def issue_access_token(*, session: Session, email: str, password: str) -> str:
    """Authenticate a user and return a bearer token payload value."""

    user = authenticate(session=session, email=email, password=password)
    if user is None:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError
    return create_access_token(
        user.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def send_password_recovery_if_registered(*, session: Session, email: str) -> None:
    """Send recovery mail without revealing whether the user exists."""

    user = get_user_by_email(session=session, email=email)
    if user is None:
        return
    token = utils.generate_password_reset_token(email=email)
    email_data = utils.generate_reset_password_email(
        email_to=user.email,
        email=email,
        token=token,
    )
    utils.send_email(
        email_to=user.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )


def reset_password(*, session: Session, token: str, new_password: str) -> None:
    """Apply a password reset token to an active user."""

    email = utils.verify_password_reset_token(token=token)
    if not email:
        raise InvalidResetTokenError
    user = get_user_by_email(session=session, email=email)
    if user is None:
        raise InvalidResetTokenError
    if not user.is_active:
        raise InactiveUserError
    update_user(
        session=session,
        db_user=user,
        user_in=UserUpdate(password=new_password),
    )


def get_password_recovery_content(
    *, session: Session, email: str
) -> PasswordRecoveryContent:
    """Build recovery email content for the administrator-only preview endpoint."""

    user = get_user_by_email(session=session, email=email)
    if user is None:
        raise UserNotFoundError
    token = utils.generate_password_reset_token(email=email)
    email_data = utils.generate_reset_password_email(
        email_to=user.email,
        email=email,
        token=token,
    )
    return PasswordRecoveryContent(
        html_content=email_data.html_content,
        subject=email_data.subject,
    )


__all__ = [
    "DUMMY_HASH",
    "EmailAlreadyExistsError",
    "IdentityServiceError",
    "InactiveUserError",
    "IncorrectPasswordError",
    "InsufficientPrivilegesError",
    "InvalidCredentialsError",
    "InvalidResetTokenError",
    "PasswordRecoveryContent",
    "PasswordReuseError",
    "SelfDeletionForbiddenError",
    "UserNotFoundError",
    "authenticate",
    "create_managed_user",
    "create_private_user",
    "create_user",
    "delete_current_user",
    "delete_managed_user",
    "get_password_recovery_content",
    "get_user_by_email",
    "get_visible_user",
    "issue_access_token",
    "list_users",
    "register_user",
    "reset_password",
    "resolve_token_user",
    "send_password_recovery_if_registered",
    "update_current_password",
    "update_current_user",
    "update_managed_user",
    "update_user",
]
