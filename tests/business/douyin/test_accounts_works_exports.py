"""抖音账号管理与作品导出的测试：覆盖远程浏览器槽位发现与独占绑定、登录容错、身份校验复用、账号/账号池 CRUD 与轮询调度、任务拆分、作品列表排序筛选及评论/字幕导出。"""

import uuid
from datetime import timedelta

import httpx
import pytest
from crawler.bootstrap.settings import settings
from crawler.business.common.models import get_datetime_utc
from crawler.business.douyin.accounts import service as account_service
from crawler.business.douyin.accounts.models import (
    DouyinAccount,
    DouyinAccountPoolStrategy,
)
from crawler.business.douyin.accounts.service import AccountConfigurationError
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


def test_remote_browser_slots_are_discoverable_and_exclusive(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证远程浏览器槽位可被发现（CDP 健康、活动页信息脱敏），槽位被账号绑定后互斥且重复绑定返回 422。"""

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
    assert payload["count"] == 2
    assert [item["name"] for item in payload["data"]] == [
        None,
        "test-slot-exclusive",
    ]
    named_slot = next(
        item for item in payload["data"] if item["name"] == "test-slot-exclusive"
    )
    assert named_slot["available"] is True
    assert named_slot["cdp_healthy"] is True
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
            "remote_slot": "test-slot-exclusive",
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
            "remote_slot": "test-slot-exclusive",
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


def test_login_keeps_connected_browser_when_douyin_navigation_fails(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证登录时抖音首页导航失败（如代理不通）仍保留已连接浏览器，账号进入 verifying 状态并记录原因。"""

    class FakePage:
        """模拟页面：goto 始终抛出网络错误。"""

        async def goto(self, *_args: object, **_kwargs: object) -> None:
            """模拟导航失败（代理连接失败）。"""
            raise PlaywrightError("net::ERR_PROXY_CONNECTION_FAILED")

    class FakeBrowser:
        """模拟 CDP 浏览器会话：可启动产生页面，但页面导航会失败。"""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.page: FakePage | None = None

        async def start(self) -> None:
            """启动会话并创建模拟页面。"""
            self.page = FakePage()

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

    class FakePage:
        """模拟页面：记录导航次数。"""

        async def goto(self, *_args: object, **_kwargs: object) -> None:
            """模拟成功导航并累计调用次数。"""
            nonlocal navigation_calls
            navigation_calls += 1
            return None

    class FakeBrowser:
        """模拟 CDP 浏览器会话：可启动并产出页面与上下文。"""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.page: FakePage | None = None
            self.context: object | None = None

        async def start(self) -> None:
            """启动会话并创建模拟页面与浏览器上下文。"""
            self.page = FakePage()
            self.context = object()

        async def close(self) -> None:
            """关闭会话（空实现）。"""
            return None

    class FakeClient:
        """模拟抖音客户端：心跳正常但获取个人资料接口抛错。"""

        @classmethod
        async def create(cls, **_kwargs: object) -> "FakeClient":
            """创建模拟客户端实例。"""
            return cls()

        async def pong(
            self, _context: object, require_self_profile: bool = False
        ) -> bool:
            """模拟登录心跳检测，断言不强制拉取个人资料。"""
            assert require_self_profile is False
            return True

        async def get_self_profile(self) -> dict[str, object]:
            """模拟个人资料接口被临时风控。"""
            raise RuntimeError("profile endpoint temporarily blocked")

        async def close(self) -> None:
            """关闭客户端（空实现）。"""
            return None

    monkeypatch.setattr(account_service, "CDPBrowserSession", FakeBrowser)
    monkeypatch.setattr(account_service, "DouyinClient", FakeClient)
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
