"""前端展示文案配置字段。"""

from pydantic import BaseModel, Field


class UiLabelsConfig(BaseModel):
    """前端展示文案（可由 config.yaml 覆盖的字典）。

    目前只承载账号状态文案；前端会先按内置默认渲染，取到接口结果后再覆盖，
    因此这里缺键或接口失败都不会影响页面可用性。
    """

    account_status: dict[str, str] = Field(default_factory=dict)


class UiFields(BaseModel):
    """前端展示层配置。"""

    UI_LABELS: UiLabelsConfig = (
        UiLabelsConfig()
    )  # 前端展示文案（字典）；缺键时前端用内置默认
