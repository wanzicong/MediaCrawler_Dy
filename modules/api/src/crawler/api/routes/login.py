from typing import Annotated, Any

from crawler.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from crawler.business.common.models import Message
from crawler.business.identity import service as identity_service
from crawler.business.identity.models import (
    NewPassword,
    Token,
    UserPublic,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(tags=["login"])


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    try:
        return Token(
            access_token=identity_service.issue_access_token(
                session=session,
                email=form_data.username,
                password=form_data.password,
            )
        )
    except identity_service.InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=400, detail="Incorrect email or password"
        ) from exc
    except identity_service.InactiveUserError as exc:
        raise HTTPException(status_code=400, detail="Inactive user") from exc


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    """
    Password Recovery
    """
    # Always return the same response to prevent email enumeration attacks
    # Only send email if user actually exists
    identity_service.send_password_recovery_if_registered(
        session=session,
        email=email,
    )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    try:
        identity_service.reset_password(
            session=session,
            token=body.token,
            new_password=body.new_password,
        )
    except identity_service.InvalidResetTokenError as exc:
        # Don't reveal that the user doesn't exist - use same error as invalid token
        raise HTTPException(status_code=400, detail="Invalid token") from exc
    except identity_service.InactiveUserError as exc:
        raise HTTPException(status_code=400, detail="Inactive user") from exc
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    try:
        email_data = identity_service.get_password_recovery_content(
            session=session,
            email=email,
        )
    except identity_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        ) from exc

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )
