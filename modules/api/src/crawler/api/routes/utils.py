"""工具类路由：邮件发送测试与服务健康检查接口。"""

from crawler.api.deps import get_current_active_superuser
from crawler.business.common.models import Message
from crawler.business.identity.mail import generate_test_email, send_email
from fastapi import APIRouter, Depends
from pydantic.networks import EmailStr

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """向指定邮箱发送测试邮件（仅超级管理员可用）。

    参数：
        email_to: 接收测试邮件的邮箱地址。

    返回：
        发送结果消息。
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    """服务健康检查接口，存活即返回 True。"""
    return True
