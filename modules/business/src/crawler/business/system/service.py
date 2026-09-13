"""系统展示层的应用服务：只读地把配置里的展示元数据交给入站适配层。

目前只有一个用例——前端展示文案（``config.yaml`` 的 ``ui.labels``）。它不碰数据库，
也不持有状态：文案缺失时返回空映射，由前端内置默认兜底。
"""

from crawler.bootstrap.settings import settings
from crawler.business.system.models import UiLabelsPublic


def ui_labels_public() -> UiLabelsPublic:
    """返回前端展示文案（账号状态等）。

    返回：
        UiLabelsPublic；``account_status`` 为「状态值 → 文案」映射，缺省时为空字典。
    """
    return UiLabelsPublic(account_status=dict(settings.UI_LABELS.account_status))


__all__ = ["ui_labels_public"]
