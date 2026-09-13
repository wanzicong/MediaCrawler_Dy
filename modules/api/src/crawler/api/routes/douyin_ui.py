"""抖音前端文案路由：把展示层文案（账号状态等）下发给前端。

文案来自 ``config.yaml`` 的 ``ui.labels``，前端先用内置默认渲染、取到结果后再覆盖，
因此文案缺失或接口失败都不会影响页面可用性。
"""

from typing import Any

from crawler.api.deps import CurrentUser
from crawler.business.system.models import UiLabelsPublic
from crawler.business.system.service import ui_labels_public
from fastapi import APIRouter

router = APIRouter(prefix="/douyin/ui-labels", tags=["douyin-ui"])


@router.get("", response_model=UiLabelsPublic)
def get_ui_labels(_current_user: CurrentUser) -> Any:
    """返回前端展示文案（账号状态等）。

    参数：
        _current_user: 当前登录用户；仅用于鉴权，文案内容与用户无关。
    返回：
        文案映射（缺键时由前端内置默认兜底）。
    """
    return ui_labels_public()


__all__ = ["get_ui_labels", "router"]
