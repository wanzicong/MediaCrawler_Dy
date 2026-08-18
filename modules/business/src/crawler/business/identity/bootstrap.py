"""Identity bootstrap use case for the initial administrator account."""

from crawler.bootstrap.settings import settings
from crawler.business.identity import service
from crawler.business.identity.models import User, UserCreate
from sqlmodel import Session, select


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
