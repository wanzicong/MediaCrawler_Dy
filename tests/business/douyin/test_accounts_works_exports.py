"""抖音账号管理与作品导出的测试：覆盖本机/远程浏览器槽位发现与独占绑定、账号到槽位 Profile 的解析、登录容错、身份校验复用、账号/账号池 CRUD 与轮询调度、任务拆分、作品列表排序筛选及评论/字幕导出。"""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from crawler.bootstrap.settings import (
    BrowserSlotLocalConfig,
    BrowserSlotRemoteConfig,
    BrowserSlotsConfig,
    Settings,
    settings,
)
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts import service as account_service
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinAccountPoolStrategy,
    DouyinAccountStatus,
)
from crawler.business.douyin.accounts.service import AccountConfigurationError
from crawler.business.douyin.adapters import service as adapter_service
from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import (
    DouyinMediaAsset,
    DouyinSubtitle,
    MediaDownloadStatus,
    SubtitleStatus,
)
from crawler.business.douyin.tasks.models import (
    CrawlTask,
    CrawlTaskCreate,
    CrawlTaskPhase,
)
from crawler.business.douyin.tasks.service import DouyinTaskManager
from crawler.business.identity.models import User
from fastapi.testclient import TestClient
from playwright.async_api import Error as PlaywrightError
from sqlmodel import Session, select

from tests.utils.douyin import default_track_id


class FakeSessionContext:
    """登录用例的最小会话能力替身，满足只读页面端口 ``BrowserPage`` 契约。

    这些用例都把 ``DouyinClient`` 整体替换成 FakeClient，不会真正消费会话内容；
    替身存在只是为了让「建会话 → 取只读页面端口 → 建客户端」这条链路可被走通。
    四个原语方法一律返回空值，与「缺键即不写入」的真实契约一致。
    """

    async def user_agent(self) -> str:
        """返回固定 User-Agent。"""
        return "Mozilla/5.0 (fake)"

    async def local_storage(self) -> dict[str, object]:
        """返回空 localStorage 快照。"""
        return {}

    async def cookies(self, urls: Sequence[str]) -> tuple[str, dict[str, str]]:
        """返回空 cookie。"""
        return "", {}

    async def fingerprint(self) -> dict[str, str]:
        """返回空指纹。"""
        return {}


def test_reserve_accounts_is_atomic_when_one_account_is_unavailable(
    db: Session,
) -> None:
    """验证账号池批量预占整体提交：任一账号不可用时不占用其余账号。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    ready = DouyinAccount(
        owner_id=owner.id,
        name=f"原子预占-可用-{uuid.uuid4().hex[:8]}",
        browser_mode="local",
        profile_key=uuid.uuid4().hex,
        identity_hash=uuid.uuid4().hex,
        status="ready",
    )
    unavailable = DouyinAccount(
        owner_id=owner.id,
        name=f"原子预占-占满-{uuid.uuid4().hex[:8]}",
        browser_mode="local",
        profile_key=uuid.uuid4().hex,
        identity_hash=uuid.uuid4().hex,
        status="busy",
        active_leases=1,
        concurrency_limit=1,
    )
    db.add(ready)
    db.add(unavailable)
    db.commit()

    with pytest.raises(AccountConfigurationError, match="账号当前不可调度"):
        account_service.reserve_accounts([ready.id, unavailable.id])

    db.expire_all()
    refreshed_ready = db.get(DouyinAccount, ready.id)
    assert refreshed_ready is not None
    assert refreshed_ready.active_leases == 0
    assert refreshed_ready.tasks_today == 0

    db.delete(unavailable)
    db.delete(refreshed_ready)
    db.commit()


def test_future_cooldown_account_is_not_reactivated_early(db: Session) -> None:
    """验证尚未到期的冷却账号不会被选号或租用逻辑提前恢复，避免触发连续风控。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    cooldown_until = get_datetime_utc() + timedelta(minutes=10)
    account = DouyinAccount(
        owner_id=owner.id,
        name=f"冷却保护-{uuid.uuid4().hex[:8]}",
        browser_mode="local",
        profile_key=uuid.uuid4().hex,
        identity_hash=uuid.uuid4().hex,
        status="cooldown",
        cooldown_until=cooldown_until,
    )
    db.add(account)
    db.commit()

    with pytest.raises(AccountConfigurationError, match="当前不可调度"):
        account_service.select_task_accounts(
            owner_id=owner.id,
            account_id=account.id,
            account_ids=[],
            pool_id=None,
            strategy=DouyinAccountPoolStrategy.least_loaded,
        )
    with pytest.raises(AccountConfigurationError, match="当前不可调度"):
        account_service.reserve_accounts([account.id])

    db.expire_all()
    refreshed = db.get(DouyinAccount, account.id)
    assert refreshed is not None
    assert refreshed.status == "cooldown"
    assert refreshed.cooldown_until == cooldown_until
    assert refreshed.active_leases == 0
    db.delete(refreshed)
    db.commit()


def test_task_public_includes_selected_account_and_pool_names(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证任务详情显式展示其执行账号和账号池，避免账号概念在任务页面中丢失。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    suffix = uuid.uuid4().hex[:8]
    account_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": f"任务展示账号-{suffix}", "browser_mode": "local"},
    )
    assert account_response.status_code == 201
    account_id = uuid.UUID(account_response.json()["id"])
    pool_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
        json={
            "name": f"任务展示账号池-{suffix}",
            "account_ids": [str(account_id)],
            "strategy": "least_loaded",
            "max_parallel_accounts": 1,
        },
    )
    assert pool_response.status_code == 201
    pool_id = uuid.UUID(pool_response.json()["id"])
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        account_id=account_id,
        account_pool_id=pool_id,
        crawl_type="search",
        status="queued",
        request_json='{"crawl_type":"search","keywords":["账号展示"]}',
    )
    db.add(task)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["account_name"] == f"任务展示账号-{suffix}"
    assert response.json()["account_pool_name"] == f"任务展示账号池-{suffix}"

    db.delete(task)
    db.commit()
    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/pools/{pool_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def _patch_cdp_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 CDP 健康探测替换为固定响应，并断言探测走直连（Host 头 + 禁用环境代理）。"""

    class FakeResponse:
        """模拟 CDP /json 接口的 HTTP 响应。"""

        def raise_for_status(self) -> None:
            """模拟响应状态正常。"""
            return None

        def json(self) -> list[dict[str, str]]:
            """返回一个指向抖音首页的活动页面条目。"""
            return [
                {
                    "type": "page",
                    "title": "抖音首页",
                    "url": "https://www.douyin.com/?sensitive=query",
                }
            ]

    def fake_get(*_args: object, **kwargs: object) -> FakeResponse:
        """模拟 httpx.get：断言走 Host 头直连且禁用环境代理。"""
        assert kwargs["headers"] == {"Host": "localhost"}
        assert kwargs["trust_env"] is False
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)


def test_remote_browser_slots_are_discoverable_and_exclusive(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证远程浏览器槽位可被发现（CDP 健康、活动页信息脱敏），槽位被账号绑定后互斥且重复绑定返回 422。"""

    _patch_cdp_probe(monkeypatch)
    monkeypatch.setattr(
        settings,
        "DOUYIN_REMOTE_CDP_SLOTS",
        '{"test-slot-exclusive":{"host":"127.0.0.1","port":9224,"viewer_url":"http://127.0.0.1:6082/vnc.html"}}',
    )

    slots = client.get(
        f"{settings.API_V1_STR}/douyin/accounts/browser-slots",
        headers=superuser_token_headers,
    )
    assert slots.status_code == 200
    payload = slots.json()
    # 本机槽位在前、远程槽位在后；本机槽位数量与配置一致（默认 4 个）
    assert payload["count"] == 2 + settings.DOUYIN_LOCAL_CDP_SLOT_COUNT
    assert [
        item["name"] for item in payload["data"] if item["browser_mode"] == "remote"
    ] == [None, "test-slot-exclusive"]
    named_slot = next(
        item for item in payload["data"] if item["name"] == "test-slot-exclusive"
    )
    assert named_slot["browser_mode"] == "remote"
    assert named_slot["available"] is True
    assert named_slot["cdp_healthy"] is True
    assert named_slot["cdp_endpoint"] == "127.0.0.1:9224"
    assert named_slot["page_count"] == 1
    assert named_slot["active_page_title"] == "抖音首页"
    assert named_slot["active_page_url"] == "https://www.douyin.com/"
    assert "viewer_url" in named_slot

    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={
            "name": "远程槽位账号",
            "browser_mode": "remote",
            "slot": "test-slot-exclusive",
        },
    )
    assert created.status_code == 201

    occupied_slots = client.get(
        f"{settings.API_V1_STR}/douyin/accounts/browser-slots",
        headers=superuser_token_headers,
    ).json()["data"]
    named = next(
        item for item in occupied_slots if item["name"] == "test-slot-exclusive"
    )
    assert named["available"] is False
    assert named["occupied_account_name"] == "远程槽位账号"

    duplicate = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={
            "name": "重复槽位账号",
            "browser_mode": "remote",
            "slot": "test-slot-exclusive",
        },
    )
    assert duplicate.status_code == 422
    assert "已绑定账号" in duplicate.json()["detail"]
    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{created.json()['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_local_browser_slots_default_to_four_distinct_browsers() -> None:
    """验证本机浏览器槽位默认 4 个：端口与 Profile 目录两两独立，槽位名连续。"""

    assert Settings.model_fields["DOUYIN_LOCAL_CDP_SLOT_COUNT"].default == 4

    slots = account_service._local_slots()
    expected_names = [
        f"local-{index}" for index in range(1, settings.DOUYIN_LOCAL_CDP_SLOT_COUNT + 1)
    ]
    assert list(slots) == expected_names
    ports = [int(str(slot["port"])) for slot in slots.values()]
    directories = [slot["user_data_dir"] for slot in slots.values()]
    assert len(set(ports)) == len(ports)
    assert len(set(directories)) == len(directories)
    assert slots["local-1"]["port"] == settings.DOUYIN_LOCAL_CDP_PORT_BASE
    assert slots["local-1"]["host"] == settings.DOUYIN_CDP_HOST
    assert (
        slots["local-1"]["user_data_dir"]
        == settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR / "local-1"
    )


def test_local_account_resolves_to_its_slot_profile_and_port() -> None:
    """验证绑定本机槽位的账号解析到槽位 Profile 与端口，且会话保留常驻浏览器。"""

    account = DouyinAccount(
        owner_id=uuid.uuid4(),
        name="本机槽位账号",
        browser_mode="local",
        profile_key="0123456789abcdef",
        slot="local-2",
    )

    spec = account_service.resolve_account_browser(account)

    assert spec.browser_mode == "local"
    assert spec.slot_name == "local-2"
    assert spec.user_data_dir == settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR / "local-2"
    assert spec.debug_port == settings.DOUYIN_LOCAL_CDP_PORT_BASE + 1
    assert spec.keep_alive is True


def test_unbound_local_account_keeps_its_own_profile_directory() -> None:
    """验证未绑定槽位的历史本机账号继续使用账号独立 Profile 与派生端口。"""

    account = DouyinAccount(
        owner_id=uuid.uuid4(),
        name="历史本机账号",
        browser_mode="local",
        profile_key="fedcba9876543210",
    )

    spec = account_service.resolve_account_browser(account)

    assert spec.slot_name is None
    assert spec.keep_alive is False
    assert spec.user_data_dir == (
        settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent
        / "accounts"
        / account.profile_key
    )
    assert spec.debug_port == settings.DOUYIN_CDP_PORT + (account.id.int % 500)


def test_config_slots_override_env_derived_registry(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 config.yaml 声明的槽位接管派生规则：列表展示 label、禁用槽位被剔除、绑定受同一注册表约束。"""
    _patch_cdp_probe(monkeypatch)
    monkeypatch.setattr(
        settings,
        "BROWSER_SLOTS",
        BrowserSlotsConfig(
            local=[
                BrowserSlotLocalConfig(name="local-9", label="本机九号", port=9401),
                BrowserSlotLocalConfig(name="local-10", port=9402, enabled=False),
            ],
            remote=[
                BrowserSlotRemoteConfig(
                    name="pool-yaml",
                    label="云端 YAML 槽位",
                    host="127.0.0.1",
                    port=9299,
                    viewer_url="http://127.0.0.1:6099/vnc.html",
                )
            ],
        ),
    )
    slots_url = f"{settings.API_V1_STR}/douyin/accounts/browser-slots"

    payload = client.get(slots_url, headers=superuser_token_headers).json()
    local_slots = [item for item in payload["data"] if item["browser_mode"] == "local"]
    # 只保留启用槽位，展示名取自 label
    assert [(item["name"], item["label"]) for item in local_slots] == [
        ("local-9", "本机九号")
    ]
    # 云端保留始终存在的 Docker 默认槽位，其余来自 YAML
    assert [
        (item["name"], item["label"])
        for item in payload["data"]
        if item["browser_mode"] == "remote"
    ] == [(None, "Docker 默认槽位"), ("pool-yaml", "云端 YAML 槽位")]
    assert all(item["configured"] for item in payload["data"])

    # 注册表同样以 YAML 为准：端口与 Profile 目录来自声明
    registry = account_service._local_slots()
    assert list(registry) == ["local-9"]
    assert registry["local-9"]["port"] == 9401
    assert registry["local-9"]["user_data_dir"] == (
        settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR / "local-9"
    )
    # 远程注册表也只含 YAML 声明的槽位（.env 里的 pool-1..3 JSON 被接管）
    assert list(account_service._remote_slots()) == ["pool-yaml"]

    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "YAML 槽位账号", "browser_mode": "local", "slot": "local-9"},
    )
    assert created.status_code == 201
    assert created.json()["slot"] == "local-9"

    # YAML 接管后，没声明的派生槽位与显式禁用的槽位都不可绑定
    for slot in ("local-1", "local-10"):
        rejected = client.post(
            f"{settings.API_V1_STR}/douyin/accounts",
            headers=superuser_token_headers,
            json={
                "name": f"非法槽位账号-{slot}",
                "browser_mode": "local",
                "slot": slot,
            },
        )
        assert rejected.status_code == 422
        assert "未配置" in rejected.json()["detail"]

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{created.json()['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_local_accounts_without_slot_can_coexist(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证未绑定槽位的本机账号各自使用独立 Profile，可同时存在而不触发槽位独占。"""

    account_ids: list[str] = []
    for suffix in ("甲", "乙"):
        response = client.post(
            f"{settings.API_V1_STR}/douyin/accounts",
            headers=superuser_token_headers,
            json={"name": f"未绑定槽位账号-{suffix}", "browser_mode": "local"},
        )
        assert response.status_code == 201
        assert response.json()["slot"] is None
        account_ids.append(response.json()["id"])

    for account_id in account_ids:
        assert (
            client.delete(
                f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
                headers=superuser_token_headers,
            ).status_code
            == 200
        )


def test_local_profile_directory_stays_inside_managed_roots() -> None:
    """验证删除账号时待清理的 Profile 目录只落在受管根目录内。"""

    slot_account = DouyinAccount(
        owner_id=uuid.uuid4(),
        name="槽位账号",
        browser_mode="local",
        profile_key="0123456789abcdef",
        slot="local-3",
    )
    legacy_account = DouyinAccount(
        owner_id=uuid.uuid4(),
        name="历史账号",
        browser_mode="local",
        profile_key="fedcba9876543210",
    )
    remote_account = DouyinAccount(
        owner_id=uuid.uuid4(),
        name="远程账号",
        browser_mode="remote",
        profile_key="0011223344556677",
        slot="pool-1",
    )

    assert (
        account_service.local_account_profile_dir(slot_account)
        == settings.DOUYIN_LOCAL_CDP_USER_DATA_DIR / "local-3"
    )
    assert account_service.local_account_profile_dir(legacy_account) == (
        settings.DOUYIN_CDP_USER_DATA_DIR.resolve().parent
        / "accounts"
        / legacy_account.profile_key
    )
    assert account_service.local_account_profile_dir(remote_account) is None


def _create_local_account(
    client: TestClient, headers: dict[str, str], name: str
) -> dict[str, Any]:
    """建一个不绑定槽位的本机账号（私有 Profile，测试里不会真连浏览器）。"""
    response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=headers,
        # 名称与派生的 Profile 键在同一用户内唯一：加随机后缀，
        # 避免同一数据库被多次 pytest 会话复用时撞名
        json={"name": f"{name}-{uuid.uuid4().hex[:8]}", "browser_mode": "local"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_enabling_account_requires_verification_when_it_was_unhealthy(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """异常状态的账号重新启用时不得直接变成 ready（否则未验证就进调度池）。"""

    account = _create_local_account(client, superuser_token_headers, "异常账号")
    account_id = uuid.UUID(account["id"])
    record = db.get(DouyinAccount, account_id)
    assert record is not None
    # 模拟「验证失败后又被停用」：有身份哈希，但状态是 unhealthy 且带错误
    record.identity_hash = "a" * 64
    record.status = DouyinAccountStatus.unhealthy.value
    record.last_error = "尚未检测到有效的抖音登录状态"
    db.add(record)
    db.commit()

    disabled = client.patch(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
        headers=superuser_token_headers,
        json={"enabled": False},
    )
    assert disabled.json()["status"] == "disabled"

    enabled = client.patch(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
        headers=superuser_token_headers,
        json={"enabled": True},
    )
    assert enabled.json()["status"] == "unhealthy"
    # 不在调度候选里：调度只收 ready/busy/cooldown
    candidates = account_service.eligible_accounts(db, owner_id=record.owner_id)
    assert account_id not in [item.id for item in candidates]


def test_enabling_verified_account_restores_ready(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """健康账号（已登录且无历史错误）停用再启用后回到 ready。"""

    account = _create_local_account(client, superuser_token_headers, "健康账号")
    account_id = uuid.UUID(account["id"])
    record = db.get(DouyinAccount, account_id)
    assert record is not None
    record.identity_hash = "b" * 64
    record.status = DouyinAccountStatus.ready.value
    record.last_error = None
    record.failure_streak = 0
    db.add(record)
    db.commit()

    for enabled_value in (False, True):
        response = client.patch(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
            json={"enabled": enabled_value},
        )
        assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_enabling_account_without_identity_requires_login(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """从没登录过的账号，停用再启用仍然要求先登录。"""

    account = _create_local_account(client, superuser_token_headers, "未登录账号")
    account_id = account["id"]
    for enabled_value in (False, True):
        response = client.patch(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
            json={"enabled": enabled_value},
        )
        assert response.status_code == 200
    assert response.json()["status"] == "login_required"


def test_startup_lease_reset_keeps_unhealthy_accounts_out_of_pool(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """服务启动清理残留租约时，不能把 unhealthy 账号静默放回调度池。"""

    account = _create_local_account(client, superuser_token_headers, "崩溃账号")
    account_id = uuid.UUID(account["id"])
    record = db.get(DouyinAccount, account_id)
    assert record is not None
    record.identity_hash = "c" * 64
    record.status = DouyinAccountStatus.unhealthy.value
    record.last_error = "任务执行失败"
    record.active_leases = 1
    db.add(record)
    db.commit()

    account_service.reset_stale_account_leases()

    db.expire_all()
    refreshed = db.get(DouyinAccount, account_id)
    assert refreshed is not None
    assert refreshed.active_leases == 0
    assert refreshed.status == DouyinAccountStatus.unhealthy.value
    candidates = account_service.eligible_accounts(db, owner_id=record.owner_id)
    assert account_id not in [item.id for item in candidates]


def test_delete_slot_account_keeps_slot_profile(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """删除绑定槽位的账号时不得删除槽位 Profile：槽位浏览器还在跑，

    运行中删掉目录会让 Chrome 下次启动重建一个全新 Profile，账号登录态
    因此凭空消失（用户反馈的「明明登录了却总丢失登录状态」）。
    """

    monkeypatch.setattr(
        settings, "DOUYIN_LOCAL_CDP_USER_DATA_DIR", tmp_path / "douyin-local"
    )
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "槽位账号", "browser_mode": "local", "slot": "local-3"},
    )
    assert created.status_code == 201

    slot_profile = tmp_path / "douyin-local" / "local-3"
    slot_profile.mkdir(parents=True, exist_ok=True)
    cookie_stub = slot_profile / "Cookies"
    cookie_stub.write_text("stub", encoding="utf-8")

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{created.json()['id']}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    # 槽位 Profile（连同其中的登录态）原地保留，只有账号记录被删除
    assert slot_profile.is_dir()
    assert cookie_stub.exists()


def test_delete_legacy_local_account_removes_its_own_profile(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未绑定槽位的历史账号用的私有 Profile 目录仍随账号一并清理。"""

    monkeypatch.setattr(settings, "DOUYIN_CDP_USER_DATA_DIR", tmp_path / "douyin")
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "历史账号", "browser_mode": "local"},
    )
    assert created.status_code == 201
    account = db.get(DouyinAccount, uuid.UUID(created.json()["id"]))
    assert account is not None

    private_profile = tmp_path / "accounts" / account.profile_key
    private_profile.mkdir(parents=True, exist_ok=True)
    (private_profile / "Cookies").write_text("stub", encoding="utf-8")

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{created.json()['id']}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    assert not private_profile.exists()


def test_local_browser_slots_are_discoverable_and_exclusive(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证本机浏览器槽位可被发现并独占绑定，未配置槽位与重复绑定都返回 422。"""

    _patch_cdp_probe(monkeypatch)
    monkeypatch.setattr(
        settings,
        "DOUYIN_REMOTE_CDP_SLOTS",
        '{"remote-probe-only":{"host":"127.0.0.1","port":9224}}',
    )
    slots_url = f"{settings.API_V1_STR}/douyin/accounts/browser-slots"

    payload = client.get(slots_url, headers=superuser_token_headers).json()
    local_slots = [item for item in payload["data"] if item["browser_mode"] == "local"]
    remote_slot = next(
        item for item in payload["data"] if item["name"] == "remote-probe-only"
    )
    assert [item["name"] for item in local_slots] == [
        f"local-{index}" for index in range(1, settings.DOUYIN_LOCAL_CDP_SLOT_COUNT + 1)
    ]
    assert local_slots[0]["label"] == "本机浏览器 1"
    assert local_slots[0]["is_default"] is False
    assert local_slots[0]["available"] is True
    assert local_slots[0]["configured"] is True
    # 本机浏览器运行在本机窗口中，没有 noVNC 之类的远程查看地址
    assert local_slots[0]["viewer_url"] is None
    assert local_slots[0]["viewer_available"] is False
    assert local_slots[0]["cdp_healthy"] is True
    assert local_slots[0]["page_count"] == 1
    assert local_slots[0]["active_page_url"] == "https://www.douyin.com/"

    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "本机槽位账号", "browser_mode": "local", "slot": "local-1"},
    )
    assert created.status_code == 201
    assert created.json()["browser_mode"] == "local"
    assert created.json()["slot"] == "local-1"

    duplicate = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "重复本机槽位账号", "browser_mode": "local", "slot": "local-1"},
    )
    assert duplicate.status_code == 422
    assert "已绑定账号" in duplicate.json()["detail"]

    unconfigured = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "未知本机槽位账号", "browser_mode": "local", "slot": "local-99"},
    )
    assert unconfigured.status_code == 422
    assert "未配置" in unconfigured.json()["detail"]

    occupied = client.get(slots_url, headers=superuser_token_headers).json()["data"]
    bound = next(item for item in occupied if item["name"] == "local-1")
    assert bound["available"] is False
    assert bound["occupied_account_name"] == "本机槽位账号"
    # 本机槽位被占用不影响远程槽位的可用性判定（槽位占用按模式隔离）
    assert remote_slot["available"] is True
    assert (
        next(item for item in occupied if item["name"] == "remote-probe-only")[
            "available"
        ]
        is True
    )

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{created.json()['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    released = client.get(slots_url, headers=superuser_token_headers).json()["data"]
    assert next(item for item in released if item["name"] == "local-1")["available"]


def test_login_keeps_connected_browser_when_douyin_navigation_fails(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证登录时抖音首页导航失败（如代理不通）仍保留已连接浏览器，账号进入 verifying 状态并记录原因。"""

    class FakeBrowser:
        """模拟 CDP 浏览器会话：可启动，但页面导航始终抛网络错误。"""

        @classmethod
        def from_spec(cls, *_args: object, **_kwargs: object) -> "FakeBrowser":
            """按连接参数构造替身（真实实现为 ``CDPBrowserSession.from_spec``）。"""
            return cls()

        async def start(self) -> None:
            """启动会话（空实现）。"""
            return None

        async def open(self, *_args: object, **_kwargs: object) -> None:
            """模拟导航失败（代理连接失败）。"""
            raise PlaywrightError("net::ERR_PROXY_CONNECTION_FAILED")

        @property
        def browser_page(self) -> FakeSessionContext:
            """返回模拟的只读页面端口。"""
            return FakeSessionContext()

        def session_context(self) -> FakeSessionContext:
            """返回模拟的会话能力端口。"""
            return FakeSessionContext()

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeBrowser)
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "页面导航异常账号", "browser_mode": "local"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    login = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/login",
        headers=superuser_token_headers,
    )
    assert login.status_code == 202
    payload = login.json()
    assert payload["account"]["status"] == "verifying"
    assert "浏览器已连接" in payload["message"]
    assert "代理不可用" in payload["account"]["last_error"]

    deleted = client.delete(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200


def test_verify_reuses_persisted_identity_when_profile_api_is_unavailable(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证个人资料接口暂时不可用时，登录校验复用已持久化的匿名身份指纹，账号仍判定为 ready 且只导航一次。"""
    navigation_calls = 0

    class FakeBrowser:
        """模拟 CDP 浏览器会话：可启动并产出只读页面端口。"""

        @classmethod
        def from_spec(cls, *_args: object, **_kwargs: object) -> "FakeBrowser":
            """按连接参数构造替身（真实实现为 ``CDPBrowserSession.from_spec``）。"""
            return cls()

        async def start(self) -> None:
            """启动会话（空实现）。"""
            return None

        async def open(self, *_args: object, **_kwargs: object) -> None:
            """模拟成功导航并累计调用次数。"""
            nonlocal navigation_calls
            navigation_calls += 1
            return None

        @property
        def browser_page(self) -> FakeSessionContext:
            """返回模拟的只读页面端口。"""
            return FakeSessionContext()

        def session_context(self) -> FakeSessionContext:
            """返回模拟的会话能力端口。"""
            return FakeSessionContext()

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    class FakeUserApi:
        """模拟用户接口客户端：个人资料接口被临时风控。"""

        async def get_self_profile(self) -> dict[str, object]:
            """模拟个人资料接口被临时风控。"""
            raise RuntimeError("profile endpoint temporarily blocked")

    class FakeClient:
        """模拟抖音客户端：心跳正常但获取个人资料接口抛错。"""

        def __init__(self) -> None:
            self.user_api = FakeUserApi()
            self.headers: dict[str, str] = {}

        @classmethod
        async def create(cls, **_kwargs: object) -> "FakeClient":
            """创建模拟客户端实例。"""
            return cls()

        async def pong(self, *, require_self_profile: bool = False) -> bool:
            """模拟登录心跳检测，断言不强制拉取个人资料。"""
            assert require_self_profile is False
            return True

        async def update_cookies(self) -> None:
            """模拟 cookie 同步（空实现）。"""
            return None

        async def close(self) -> None:
            """关闭客户端（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeBrowser)
    monkeypatch.setattr(adapter_service, "DouyinClient", FakeClient)
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "已持久化登录账号", "browser_mode": "local"},
    )
    assert created.status_code == 201
    account_id = uuid.UUID(created.json()["id"])
    account = db.get(DouyinAccount, account_id)
    assert account is not None
    account.identity_hash = "persisted-anonymous-identity"
    account.status = "ready"
    db.add(account)
    db.commit()

    verified = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/verify",
        headers=superuser_token_headers,
    )
    assert verified.status_code == 200
    assert navigation_calls == 1
    assert verified.json()["status"] == "ready"
    assert verified.json()["is_logged_in"] is True
    db.expire_all()
    persisted = db.get(DouyinAccount, account_id)
    assert persisted is not None
    assert persisted.identity_hash == "persisted-anonymous-identity"
    assert persisted.last_error is None

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_verify_rebuilds_login_session_when_browser_window_was_closed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证浏览器窗口被用户关闭后，验证接口丢弃失效句柄并重建会话，而不是抛 500。"""
    sessions: list[Any] = []

    class FakeLoginBrowser:
        """模拟 CDP 浏览器会话：可切换「窗口已关闭」状态。"""

        def __init__(self) -> None:
            """初始化会话替身并登记，便于测试断言重建次数。"""
            self.window_closed = False
            sessions.append(self)

        @classmethod
        def from_spec(cls, *_args: object, **_kwargs: object) -> "FakeLoginBrowser":
            """按连接参数构造替身（真实实现为 ``CDPBrowserSession.from_spec``）。"""
            return cls()

        async def start(self) -> None:
            """启动会话（空实现）。"""
            return None

        async def open(self, *_args: object, **_kwargs: object) -> None:
            """模拟成功导航（空实现）。"""
            return None

        def is_usable(self) -> bool:
            """窗口关闭后会话不可用（真实实现探测 page.is_closed()）。"""
            return not self.window_closed

        @property
        def browser_page(self) -> FakeSessionContext:
            """返回模拟只读页面端口；窗口已关闭时按真实行为抛 Playwright 错误。"""
            if self.window_closed:
                raise PlaywrightError(
                    "BrowserContext.cookies: Target page, context or browser "
                    "has been closed"
                )
            return FakeSessionContext()

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    class FakeUserApi:
        """模拟用户接口客户端：返回可识别身份的账号资料。"""

        async def get_self_profile(self) -> dict[str, object]:
            """返回带 uid 的资料响应。"""
            return {"user": {"uid": "closed-window-account"}}

    class FakeClient:
        """模拟抖音客户端：登录态正常。"""

        def __init__(self) -> None:
            """装配资料接口替身。"""
            self.user_api = FakeUserApi()
            self.headers: dict[str, str] = {}

        @classmethod
        async def create(cls, **_kwargs: object) -> "FakeClient":
            """创建模拟客户端实例。"""
            return cls()

        async def pong(self, *, require_self_profile: bool = False) -> bool:
            """模拟登录心跳检测通过。"""
            return True

        async def update_cookies(self) -> None:
            """模拟 cookie 同步（空实现）。"""
            return None

        async def close(self) -> None:
            """关闭客户端（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeLoginBrowser)
    monkeypatch.setattr(adapter_service, "DouyinClient", FakeClient)

    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "关窗重连账号", "browser_mode": "local", "slot": "local-1"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    login = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/login",
        headers=superuser_token_headers,
    )
    assert login.status_code == 202
    assert len(sessions) == 1

    # 用户把浏览器窗口关掉：内存句柄还在，但会话已经不可用
    sessions[0].window_closed = True

    verified = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/verify",
        headers=superuser_token_headers,
    )
    assert verified.status_code == 200, verified.json()
    assert len(sessions) == 2, "失效会话应被丢弃并重建"
    assert verified.json()["status"] == "ready"
    assert verified.json()["is_logged_in"] is True

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_verify_maps_browser_errors_to_login_error_instead_of_500(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证「可用性检查通过但取页面时已失效」的竞态同样转成 409，而不是 500。"""

    class FakeClosedBrowser:
        """模拟可用性检查通过、但取页面时已经关闭的会话。"""

        @classmethod
        def from_spec(cls, *_args: object, **_kwargs: object) -> "FakeClosedBrowser":
            """按连接参数构造替身。"""
            return cls()

        async def start(self) -> None:
            """启动会话（空实现）。"""
            return None

        async def open(self, *_args: object, **_kwargs: object) -> None:
            """模拟成功导航（空实现）。"""
            return None

        def is_usable(self) -> bool:
            """故意报可用，覆盖「检查与使用之间失效」的竞态。"""
            return True

        @property
        def browser_page(self) -> FakeSessionContext:
            """取页面时抛 Playwright 错误（窗口此刻已被关闭）。"""
            raise PlaywrightError(
                "BrowserContext.cookies: Target page, context or browser has been closed"
            )

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeClosedBrowser)
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "竞态失效账号", "browser_mode": "local"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    login = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/login",
        headers=superuser_token_headers,
    )
    assert login.status_code == 202

    verified = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/verify",
        headers=superuser_token_headers,
    )
    assert verified.status_code == 409
    assert "浏览器会话已失效" in verified.json()["detail"]

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_verify_distinguishes_broken_session_from_logged_out(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证失败要区分「会话中断」与「确实未登录」，避免让用户误以为要重新扫码。"""

    class FakeBrokenBrowser:
        """模拟验证过程中已经不可用的会话：登录心跳必然拿不到登录标记。"""

        @classmethod
        def from_spec(cls, *_args: object, **_kwargs: object) -> "FakeBrokenBrowser":
            """按连接参数构造替身。"""
            return cls()

        async def start(self) -> None:
            """启动会话（空实现）。"""
            return None

        async def open(self, *_args: object, **_kwargs: object) -> None:
            """模拟成功导航（空实现）。"""
            return None

        def is_usable(self) -> bool:
            """会话已中断（浏览器被关闭）。"""
            return False

        @property
        def browser_page(self) -> FakeSessionContext:
            """返回模拟只读页面端口。"""
            return FakeSessionContext()

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    class FakeUserApi:
        """模拟用户接口客户端：接口不可用。"""

        async def get_self_profile(self) -> dict[str, object]:
            """模拟资料接口失败。"""
            raise RuntimeError("session closed")

    class FakeClient:
        """模拟抖音客户端：拿不到登录标记。"""

        def __init__(self) -> None:
            """装配资料接口替身。"""
            self.user_api = FakeUserApi()
            self.headers: dict[str, str] = {}

        @classmethod
        async def create(cls, **_kwargs: object) -> "FakeClient":
            """创建模拟客户端实例。"""
            return cls()

        async def pong(self, *, require_self_profile: bool = False) -> bool:
            """模拟心跳检测无法确认登录态。"""
            return False

        async def update_cookies(self) -> None:
            """模拟 cookie 同步（空实现）。"""
            return None

        async def close(self) -> None:
            """关闭客户端（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeBrokenBrowser)
    monkeypatch.setattr(adapter_service, "DouyinClient", FakeClient)
    created = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={"name": "会话中断账号", "browser_mode": "local"},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    verified = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}/verify",
        headers=superuser_token_headers,
    )
    assert verified.status_code == 409
    assert "会话已中断" in verified.json()["detail"]

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_managed_account_and_pool_crud(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """验证托管账号与账号池的创建、列表查询、停用状态流转及删除，且响应不暴露身份指纹等内部字段。"""
    account_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts",
        headers=superuser_token_headers,
        json={
            "name": "测试本机账号",
            "browser_mode": "local",
            "daily_task_limit": 12,
        },
    )
    assert account_response.status_code == 201
    account = account_response.json()
    assert account["status"] == "login_required"
    assert "identity_hash" not in account
    assert "profile_key" not in account

    pool_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
        json={
            "name": "测试账号池",
            "account_ids": [account["id"]],
            "strategy": "least_loaded",
            "max_parallel_accounts": 1,
        },
    )
    assert pool_response.status_code == 201
    pool = pool_response.json()
    assert [item["id"] for item in pool["accounts"]] == [account["id"]]

    list_response = client.get(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
    )
    assert list_response.status_code == 200
    assert any(item["id"] == pool["id"] for item in list_response.json()["data"])

    disabled = client.patch(
        f"{settings.API_V1_STR}/douyin/accounts/by-id/{account['id']}",
        headers=superuser_token_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/pools/{pool['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/by-id/{account['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_request_round_robin_strategy_rotates_pool_accounts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证请求级轮询策略在连续两次选号时轮换池内账号，避免单账号连续承压。"""
    account_ids: list[uuid.UUID] = []
    name_prefix = uuid.uuid4().hex[:8]
    for index in range(2):
        response = client.post(
            f"{settings.API_V1_STR}/douyin/accounts",
            headers=superuser_token_headers,
            json={
                "name": f"轮询测试账号 {name_prefix}-{index}",
                "browser_mode": "local",
            },
        )
        assert response.status_code == 201
        account_id = uuid.UUID(response.json()["id"])
        account_ids.append(account_id)
        account = db.get(DouyinAccount, account_id)
        assert account is not None
        account.identity_hash = uuid.uuid4().hex
        account.status = "ready"
        db.add(account)
    db.commit()

    pool_response = client.post(
        f"{settings.API_V1_STR}/douyin/accounts/pools",
        headers=superuser_token_headers,
        json={
            "name": f"请求级轮询测试池 {name_prefix}",
            "account_ids": [str(item) for item in account_ids],
            "strategy": "least_loaded",
            "max_parallel_accounts": 1,
        },
    )
    assert pool_response.status_code == 201
    pool_id = uuid.UUID(pool_response.json()["id"])

    first = account_service.select_task_accounts(
        owner_id=db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER))
        .one()
        .id,
        account_id=None,
        account_ids=[],
        pool_id=pool_id,
        strategy=DouyinAccountPoolStrategy.round_robin,
    )
    second = account_service.select_task_accounts(
        owner_id=db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER))
        .one()
        .id,
        account_id=None,
        account_ids=[],
        pool_id=pool_id,
        strategy=DouyinAccountPoolStrategy.round_robin,
    )
    assert len(first) == len(second) == 1
    assert first[0].id != second[0].id

    assert (
        client.delete(
            f"{settings.API_V1_STR}/douyin/accounts/pools/{pool_id}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    for account_id in account_ids:
        assert (
            client.delete(
                f"{settings.API_V1_STR}/douyin/accounts/by-id/{account_id}",
                headers=superuser_token_headers,
            ).status_code
            == 200
        )


def test_task_targets_are_split_across_managed_accounts() -> None:
    """验证多账号任务拆分时关键词与采集配额被完整分摊，且子任务默认不携带媒体下载开关。"""
    owner_id = uuid.uuid4()
    accounts = [
        DouyinAccount(
            owner_id=owner_id,
            name=f"账号 {index}",
            browser_mode="local",
            profile_key=uuid.uuid4().hex,
            identity_hash=uuid.uuid4().hex,
            status="ready",
        )
        for index in range(2)
    ]
    request = CrawlTaskCreate(
        crawl_type="search",
        keywords=["FastAPI", "Python", "SQLModel"],
        max_awemes=9,
        account_ids=[item.id for item in accounts],
    )
    assignments = DouyinTaskManager._split_assignments(request, accounts)
    assert len(assignments) == 2
    assert sum(len(item.keywords) for _, item in assignments) == 3
    assert sum(item.max_awemes for _, item in assignments) == 9
    assert all(not item.download_media for _, item in assignments)


def test_unified_works_sort_time_and_exports(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """验证作品统一列表的排序与时间字段、素材库筛选与作者聚合、评论排序，以及评论 CSV 与字幕 SRT 导出内容。"""
    owner = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    task = CrawlTask(
        owner_id=owner.id,
        track_id=default_track_id(db, owner_id=owner.id),
        crawl_type="detail",
        status="succeeded",
        request_json='{"crawl_type":"detail","video_ids":["work-a","work-b"]}',
        checkpoint_json=(
            '{"version":1,"phase":"'
            + CrawlTaskPhase.completed.value
            + '","crawl_type":"detail","position":{}}'
        ),
        aweme_count=2,
        comment_count=2,
    )
    db.add(task)
    db.flush()
    first = DouyinAweme(
        task_id=task.id,
        aweme_id="work-a",
        creator_hash="creator-a",
        title="较早作品",
        nickname="甲***者",
        create_time=1_700_000_000,
        liked_count=10,
        comment_count=20,
    )
    second = DouyinAweme(
        task_id=task.id,
        aweme_id="work-b",
        creator_hash="creator-b",
        title="高赞作品",
        nickname="乙***者",
        create_time=1_710_000_000,
        liked_count=999,
        comment_count=3,
    )
    db.add(first)
    db.add(second)
    db.flush()
    db.add(
        DouyinComment(
            task_id=task.id,
            comment_id="comment-a",
            aweme_id=first.aweme_id,
            content="第一条评论",
            nickname="评***者",
            create_time=1_700_000_100,
            like_count=3,
        )
    )
    db.add(
        DouyinComment(
            task_id=task.id,
            comment_id="comment-b",
            aweme_id=first.aweme_id,
            content="第二条评论",
            nickname="另***者",
            create_time=1_700_000_200,
            like_count=9,
        )
    )
    asset = DouyinMediaAsset(
        task_id=task.id,
        aweme_id=first.aweme_id,
        status=MediaDownloadStatus.downloaded.value,
        progress=100,
    )
    db.add(asset)
    db.flush()
    db.add(
        DouyinSubtitle(
            asset_id=asset.id,
            task_id=task.id,
            aweme_id=first.aweme_id,
            status=SubtitleStatus.completed.value,
            progress=100,
            full_text="测试字幕正文",
            segments_json=('[{"start":0.0,"end":1.5,"text":"测试字幕正文"}]'),
        )
    )
    db.commit()

    works = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/works",
        params={"sort_by": "liked_count", "sort_order": "desc"},
        headers=superuser_token_headers,
    )
    assert works.status_code == 200
    payload = works.json()
    assert [row["aweme"]["aweme_id"] for row in payload["data"]] == [
        "work-b",
        "work-a",
    ]
    assert payload["data"][1]["persisted_comment_count"] == 2
    assert payload["data"][1]["aweme"]["create_time"] == 1_700_000_000
    assert payload["data"][1]["media"]["subtitle"]["full_text"] == "测试字幕正文"

    library = client.get(
        f"{settings.API_V1_STR}/douyin/library/works",
        params={
            "task_id": str(task.id),
            "creator_hash": "creator-a",
            "search": "work-a",
            "sort_by": "file_size",
        },
        headers=superuser_token_headers,
    )
    assert library.status_code == 200
    assert library.json()["count"] == 1
    assert library.json()["data"][0]["aweme"]["aweme_id"] == "work-a"

    creators = client.get(
        f"{settings.API_V1_STR}/douyin/library/creators",
        params={"task_id": str(task.id)},
        headers=superuser_token_headers,
    )
    assert creators.status_code == 200
    assert creators.json()["data"][0]["creator_hash"] == "creator-a"
    assert creators.json()["data"][0]["work_count"] == 1

    comments = client.get(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/comments",
        params={
            "aweme_id": first.aweme_id,
            "sort_by": "like_count",
            "sort_order": "desc",
        },
        headers=superuser_token_headers,
    )
    assert comments.status_code == 200
    assert [item["like_count"] for item in comments.json()["data"]] == [9, 3]
    assert comments.json()["data"][0]["create_time"] == 1_700_000_200

    comment_export = client.post(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/exports/comments",
        headers=superuser_token_headers,
        json={"aweme_ids": [first.aweme_id]},
    )
    assert comment_export.status_code == 200
    assert comment_export.content.startswith(b"\xef\xbb\xbf")
    exported_text = comment_export.content.decode("utf-8-sig")
    assert "第一条评论" in exported_text
    assert "评论时间：2023" in exported_text

    subtitle_export = client.post(
        f"{settings.API_V1_STR}/douyin/tasks/{task.id}/exports/subtitles",
        headers=superuser_token_headers,
        json={"aweme_ids": [first.aweme_id], "format": "srt"},
    )
    assert subtitle_export.status_code == 200
    assert "00:00:00,000 --> 00:00:01,500" in subtitle_export.text
    assert "测试字幕正文" in subtitle_export.text

    db.delete(task)
    db.commit()
