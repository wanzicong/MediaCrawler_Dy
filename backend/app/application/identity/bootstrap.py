"""Identity bootstrap use case for the initial administrator account."""

from sqlmodel import Session, select

from app.application.identity import service
from app.bootstrap.settings import settings
from app.domain.identity.models import User, UserCreate


def init_db(session: Session) -> None:
    """Create the configured initial superuser when it does not exist."""

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
