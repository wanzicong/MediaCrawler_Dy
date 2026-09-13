"""前端文案路由的测试：验证鉴权、出厂文案内容，以及配置改动能立即反映到接口。"""

from crawler.bootstrap.settings import UiLabelsConfig, settings
from crawler.business.douyin.accounts.models import DouyinAccountStatus
from fastapi.testclient import TestClient


def test_ui_labels_require_authentication(client: TestClient) -> None:
    """验证未认证访问文案接口返回 401。"""
    response = client.get(f"{settings.API_V1_STR}/douyin/ui-labels")

    assert response.status_code == 401


def test_ui_labels_cover_every_account_status(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证出厂配置为每个账号状态都提供了文案，且接口原样返回。"""
    response = client.get(
        f"{settings.API_V1_STR}/douyin/ui-labels",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    labels = response.json()["account_status"]
    assert set(labels) == {status.value for status in DouyinAccountStatus}
    assert all(value.strip() for value in labels.values())


def test_ui_labels_follow_config(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    """验证 config.yaml 的 ui.labels 改动会原样出现在接口响应里。"""
    monkeypatch.setattr(
        settings,
        "UI_LABELS",
        UiLabelsConfig(account_status={DouyinAccountStatus.ready.value: "自定义可用"}),
    )

    response = client.get(
        f"{settings.API_V1_STR}/douyin/ui-labels",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["account_status"] == {
        DouyinAccountStatus.ready.value: "自定义可用"
    }
