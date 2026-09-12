"""抖音互动执行器（``crawler.browser.interactions.executor``）的新实现测试。

覆盖三条流程编排（video_comment / comment_reply / message_creator）、
``api_factory`` 的调用时序（必须在主站导航成功之后）、``finally`` 中的
``api.aclose()`` 收尾，以及登录校验失败的错误分类。

替身边界：``BrowserSessionSpec`` 用真类型（冻结 dataclass，仅承载连接参数），
``CDPBrowserSession`` 用 monkeypatch 换成假会话；抖音读写能力用只实现规格
§4.3 那 5 个方法的 ``InteractionApi`` 替身。页面级协作模块
（navigation/panel/comment_locator/submit_flow）按需换成替身。
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.bootstrap.settings import settings
from crawler.browser.errors import CDPConnectionError, InteractionExecutionError
from crawler.browser.facade.spec import BrowserSessionSpec
from crawler.browser.interactions import navigation, panel, verification
from crawler.browser.interactions.comment_locator import CommentLocator
from crawler.browser.interactions.executor import DouyinInteractionExecutor
from crawler.browser.interactions.models import (
    InteractionExecutionRequest,
    InteractionExecutionResult,
)
from crawler.browser.interactions.navigation import INDEX_URL
from crawler.browser.interactions.submit_flow import SubmitFlow

VIDEO_URL = "https://www.douyin.com/video/123"


class FakeInteractionApi:
    """``InteractionApi`` 替身：只实现规格 §4.3 的 5 个方法并记录调用。"""

    def __init__(
        self,
        *,
        logged_in: bool = True,
        sec_uid: str | None = "author-sec-id",
        events: list[str] | None = None,
    ) -> None:
        """预置登录结论与作者 sec_uid；events 用于断言调用顺序。"""
        self.logged_in = logged_in
        self.sec_uid = sec_uid
        self.events = events if events is not None else []
        self.login_checks: list[bool] = []
        self.refresh_calls = 0
        self.aclose_calls = 0
        self.resolved_aweme_ids: list[str] = []

    async def verify_login(self, *, require_self_profile: bool = False) -> bool:
        """记录登录校验（含 require_self_profile 取值）并返回预置结论。"""
        self.events.append("verify_login")
        self.login_checks.append(require_self_profile)
        return self.logged_in

    async def verify_target_comment(
        self,
        *,
        aweme_id: str,
        comment_id: str,
        parent_comment_id: str | None = None,
    ) -> str:
        """返回预置的评论存在性结论（本文件不覆盖该翻译分支）。"""
        self.events.append("verify_target_comment")
        return "present"

    async def resolve_video_author_sec_uid(self, aweme_id: str) -> str | None:
        """记录作品 ID 并返回预置作者 sec_uid。"""
        self.events.append("resolve_video_author_sec_uid")
        self.resolved_aweme_ids.append(aweme_id)
        return self.sec_uid

    async def refresh_cookies(self) -> None:
        """记录 cookie 同步调用。"""
        self.events.append("refresh_cookies")
        self.refresh_calls += 1

    async def aclose(self) -> None:
        """记录端口关闭调用（executor 的 finally 必须调用它）。"""
        self.events.append("aclose")
        self.aclose_calls += 1


def _spec() -> BrowserSessionSpec:
    """构造一个本地 profile 连接参数。"""
    return BrowserSessionSpec(
        browser_mode="local",
        user_data_dir=Path("profile"),
        debug_port=9222,
    )


def _result(platform_id: str | None = None) -> InteractionExecutionResult:
    """构造一个互动执行结果。"""
    return InteractionExecutionResult(platform_id=platform_id)


def _fake_page(*, url: str = VIDEO_URL, events: list[str] | None = None) -> MagicMock:
    """构造一个可导航的假 Playwright 页面，goto 目标记入 events。"""
    page = MagicMock()
    page.url = url
    page.is_closed.return_value = False
    page.bring_to_front = AsyncMock()
    page.wait_for_timeout = AsyncMock()

    async def goto(target: str, **_kwargs: object) -> None:
        """记录导航目标（模拟 page.goto）。"""
        if events is not None:
            events.append(f"goto:{target}")

    page.goto = AsyncMock(side_effect=goto)
    return page


def _install_session(
    monkeypatch: pytest.MonkeyPatch,
    page: MagicMock,
    *,
    page_handle_error: Exception | None = None,
) -> dict[str, object]:
    """把 executor 的会话类换成假会话，返回调用记录。"""
    captured: dict[str, object] = {"opened": 0, "closed": 0, "spec": None}

    class FakeBrowserSession:
        """假 CDP 会话：只提供 executor 编排所需的页面与标签页计数。"""

        def __init__(self, config: object) -> None:
            """记录配置对象（连接参数由 from_spec 负责搬运）。"""
            self.config = config
            self.unrelated_page_count = 2

        @classmethod
        def from_spec(
            cls,
            config: object,
            spec: BrowserSessionSpec,
            *,
            reuse_existing_page: bool = False,
            close_page_on_exit: bool = True,
            page_marker: str | None = None,
        ) -> "FakeBrowserSession":
            """记录连接参数与会话选项，返回一个假会话。"""
            captured["spec"] = spec
            captured["from_spec_kwargs"] = {
                "reuse_existing_page": reuse_existing_page,
                "close_page_on_exit": close_page_on_exit,
                "page_marker": page_marker,
            }
            return cls(config)

        async def __aenter__(self) -> "FakeBrowserSession":
            """进入会话作用域。"""
            captured["opened"] = int(captured["opened"]) + 1
            return self

        async def __aexit__(self, *_args: object) -> None:
            """退出会话作用域（模拟 close()）。"""
            captured["closed"] = int(captured["closed"]) + 1

        @property
        def browser_page(self) -> object:
            """上层唯一可用的只读页面端口。"""
            return page

        @property
        def page_handle(self) -> object:
            """browser 内部专用句柄；未就绪时抛 CDPConnectionError。"""
            if page_handle_error is not None:
                raise page_handle_error
            handle = MagicMock()
            handle.page = page
            return handle

    monkeypatch.setattr(
        "crawler.browser.interactions.executor.CDPBrowserSession", FakeBrowserSession
    )
    return captured


@pytest.fixture()
def executor() -> DouyinInteractionExecutor:
    """按真实签名（settings）构造执行器。"""
    return DouyinInteractionExecutor(settings)


_MISSING = object()


def _stub_page_flow(
    monkeypatch: pytest.MonkeyPatch,
    page: MagicMock,
    *,
    editor: object = _MISSING,
    result: InteractionExecutionResult | None = None,
) -> AsyncMock:
    """把三条流程共用的页面协作者换成替身，返回 ``fill_and_submit`` 替身。"""
    monkeypatch.setattr(navigation, "open_video", AsyncMock())
    monkeypatch.setattr(
        panel,
        "open_comment_panel",
        AsyncMock(return_value=(page, AsyncMock() if editor is _MISSING else editor)),
    )
    submit = AsyncMock(return_value=result if result is not None else _result("cid-1"))
    monkeypatch.setattr(SubmitFlow, "fill_and_submit", submit)
    return submit


# ---- api_factory 时序与资源收尾 ----


def test_api_factory_runs_only_after_index_navigation(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """导航 → 建端口 → 校验登录 → 同步 cookie → 关闭端口的顺序被逐字钉住。

    api_factory 若在 ``open_index()`` 之前调用，适配器会拿到空 cookie/UA 并把
    「登录有效」静默判成「未登录」——这是规格点名的失败模式。
    """
    events: list[str] = []
    page = _fake_page(events=events)
    _install_session(monkeypatch, page)
    api = FakeInteractionApi(events=events)
    _stub_page_flow(monkeypatch, page)
    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    async def api_factory(browser_page: object) -> FakeInteractionApi:
        """记录建端口时机与传入的只读页面端口。"""
        seen.append(browser_page)
        events.append("api_factory")
        return api

    seen: list[object] = []
    asyncio.run(
        executor.execute(spec=_spec(), request=request, api_factory=api_factory)
    )

    assert events == [
        f"goto:{INDEX_URL}",
        "api_factory",
        "verify_login",
        "refresh_cookies",
        "aclose",
    ]
    assert seen == [page]


def test_index_navigation_failure_aborts_before_building_the_api(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """主站未完成导航时中止互动：不建端口，避免把空 cookie 误判为未登录。"""
    events: list[str] = []
    page = _fake_page(url="about:blank", events=events)
    _install_session(monkeypatch, page)
    api = FakeInteractionApi(events=events)
    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    async def api_factory(_browser_page: object) -> FakeInteractionApi:
        """记录端口构建（本用例中不应被调用）。"""
        events.append("api_factory")
        return api

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=api_factory)
        )

    assert captured.value.code == "browser_unavailable"
    assert captured.value.retryable is True
    assert "api_factory" not in events
    assert api.aclose_calls == 0


def test_api_client_is_closed_after_successful_execution(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """成功路径：finally 关闭端口、退出会话并移除对话框监听。"""
    page = _fake_page()
    captured = _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    callback = AsyncMock()

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    _stub_page_flow(monkeypatch, page)
    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    asyncio.run(
        executor.execute(
            spec=_spec(), request=request, api_factory=_factory, step_callback=callback
        )
    )

    assert api.aclose_calls == 1
    assert captured["opened"] == 1
    assert captured["closed"] == 1
    handler = page.on.call_args.args[1]
    page.remove_listener.assert_called_once_with("dialog", handler)


def test_login_check_uses_self_profile_and_reports_login_required(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """登录校验失败：login_required + 影响账号健康，且端口仍被关闭。"""
    events: list[str] = []
    page = _fake_page(events=events)
    _install_session(monkeypatch, page)
    api = FakeInteractionApi(logged_in=False, events=events)
    callback = AsyncMock()

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回登录失效的端口。"""
        return api

    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(
                spec=_spec(),
                request=request,
                api_factory=_factory,
                step_callback=callback,
            )
        )

    assert captured.value.code == "login_required"
    assert captured.value.affects_account_health is True
    assert api.login_checks == [True]
    assert api.refresh_calls == 0
    assert api.aclose_calls == 1
    assert events[-1] == "aclose"
    assert [call.args[1] for call in callback.await_args_list] == [
        "browser_connected",
        "execution_failed",
    ]


def test_api_client_is_not_closed_when_the_factory_itself_fails(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """端口构建抛异常时 api 仍为 None：不调用 aclose，异常原样上抛。"""
    page = _fake_page()
    captured = _install_session(monkeypatch, page)
    callback = AsyncMock()

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """模拟适配器在导航后建连失败。"""
        raise RuntimeError("adapter exploded")

    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    with pytest.raises(RuntimeError, match="adapter exploded"):
        asyncio.run(
            executor.execute(
                spec=_spec(),
                request=request,
                api_factory=_factory,
                step_callback=callback,
            )
        )

    assert captured["closed"] == 1
    assert [call.args[1] for call in callback.await_args_list] == [
        "browser_connected",
        "execution_failed",
    ]


def test_unavailable_page_handle_is_translated_to_browser_unavailable(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """页面句柄不可用时（会话未就绪）翻译为 browser_unavailable，而非裸 CDP 异常。"""
    page = _fake_page()
    captured = _install_session(
        monkeypatch, page, page_handle_error=CDPConnectionError("未启动")
    )
    api = FakeInteractionApi()

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """本用例不应走到建端口。"""
        return api

    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    with pytest.raises(InteractionExecutionError) as captured_error:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=_factory)
        )

    assert captured_error.value.code == "browser_unavailable"
    assert captured_error.value.retryable is True
    assert captured_error.value.affects_account_health is True
    assert api.aclose_calls == 0
    assert captured["closed"] == 1


def test_execute_forwards_spec_and_readonly_page_to_the_factory(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """连接参数逐字段搬进会话；factory 拿到的是只读端口，且步骤里带上隔离标签页数。"""
    page = _fake_page()
    captured = _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    callback = AsyncMock()
    seen: list[object] = []

    async def _factory(browser_page: object) -> FakeInteractionApi:
        """记录传入的只读端口。"""
        seen.append(browser_page)
        return api

    _stub_page_flow(monkeypatch, page)
    spec = _spec()
    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    asyncio.run(
        executor.execute(
            spec=spec, request=request, api_factory=_factory, step_callback=callback
        )
    )

    assert captured["spec"] is spec
    assert captured["from_spec_kwargs"] == {
        "reuse_existing_page": False,
        "close_page_on_exit": False,
        "page_marker": DouyinInteractionExecutor.interaction_page_marker,
    }
    assert seen == [page]
    connected = callback.await_args_list[0]
    assert connected.args[1] == "browser_connected"
    assert "2" in connected.args[2]


# ---- 三条流程 ----


def test_video_comment_flow_requires_confirmation_and_reports_steps(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """评论作品：按序上报步骤，并以「需显式提交 + 需平台确认」提交评论。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    callback = AsyncMock()
    editor = AsyncMock()
    submit = _stub_page_flow(monkeypatch, page, editor=editor, result=_result("cid-1"))

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    result = asyncio.run(
        executor.execute(
            spec=_spec(), request=request, api_factory=_factory, step_callback=callback
        )
    )

    assert result == _result("cid-1")
    assert [call.args[1] for call in callback.await_args_list] == [
        "browser_connected",
        "login_verified",
        "video_opened",
        "comment_editor_ready",
    ]
    assert submit.await_args.args[1] is editor
    assert submit.await_args.kwargs == {
        "require_explicit_submit": True,
        "require_comment_confirmation": True,
        "expected_aweme_id": "123",
    }


def test_video_comment_without_editor_is_a_terminal_failure(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """评论入口打开但没有输入框时判为 comment_not_available（终态，不重试）。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    _stub_page_flow(monkeypatch, page, editor=None)

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    request = InteractionExecutionRequest(
        interaction_type="video_comment", aweme_id="123", content="测试评论"
    )

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=_factory)
        )

    assert captured.value.code == "comment_not_available"
    assert captured.value.retryable is False
    assert api.aclose_calls == 1


def test_reply_to_comment_submits_with_the_confirmed_reply_context(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """回复评论：把已确认的回复上下文与目标/父评论 ID 一并交给提交层。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    callback = AsyncMock()
    target = MagicMock()
    reply_context = MagicMock()
    reply_editor = AsyncMock()
    submit = _stub_page_flow(monkeypatch, page, result=_result("reply-cid"))
    monkeypatch.setattr(
        CommentLocator, "ensure_comment_list_active", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        CommentLocator, "find_comment_target", AsyncMock(return_value=target)
    )
    monkeypatch.setattr(
        CommentLocator,
        "open_reply_editor",
        AsyncMock(return_value=(reply_context, reply_editor)),
    )
    request = InteractionExecutionRequest(
        interaction_type="comment_reply",
        aweme_id="123",
        content="回复",
        target_comment_id="child-2",
        target_comment_content="目标",
        target_parent_comment_id="parent-1",
    )

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    result = asyncio.run(
        executor.execute(
            spec=_spec(), request=request, api_factory=_factory, step_callback=callback
        )
    )

    assert result == _result("reply-cid")
    assert submit.await_args.kwargs["expected_reply_context"] is reply_context
    assert submit.await_args.kwargs["expected_reply_comment_id"] == "child-2"
    assert submit.await_args.kwargs["expected_parent_comment_id"] == "parent-1"
    assert "reply_target_found" in [call.args[1] for call in callback.await_args_list]


def test_reply_to_comment_without_dom_target_verifies_through_the_api(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """页面定位不到目标时先经接口核验；接口确认存在则报可重试的 target_dom_not_found。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    lookup = AsyncMock(return_value="present")
    _stub_page_flow(monkeypatch, page)
    monkeypatch.setattr(
        CommentLocator, "ensure_comment_list_active", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        CommentLocator, "find_comment_target", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(verification, "lookup_target_comment", lookup)
    request = InteractionExecutionRequest(
        interaction_type="comment_reply",
        aweme_id="123",
        content="回复",
        target_comment_id="child-2",
        target_comment_content="目标",
    )

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=_factory)
        )

    assert captured.value.code == "target_dom_not_found"
    assert captured.value.retryable is True
    assert lookup.await_args.args[0] is api
    assert api.aclose_calls == 1


def test_reply_to_comment_requires_target_content_before_any_navigation(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """缺少目标评论文案时无法在页面内定位，直接判 target_not_found 且不导航。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi()
    open_video = AsyncMock()
    monkeypatch.setattr(navigation, "open_video", open_video)
    request = InteractionExecutionRequest(
        interaction_type="comment_reply",
        aweme_id="123",
        content="回复",
        target_comment_id="child-2",
    )

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=_factory)
        )

    assert captured.value.code == "target_not_found"
    open_video.assert_not_awaited()


def test_message_creator_resolves_author_and_opens_the_creator_profile(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """私信作者：先解析作者 sec_uid，再打开作者主页并发送（不要求评论确认）。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi(sec_uid="author-sec-id")
    callback = AsyncMock()
    editor_page = MagicMock()
    editor = AsyncMock()
    open_creator = AsyncMock()
    monkeypatch.setattr(navigation, "open_creator_profile", open_creator)
    monkeypatch.setattr(
        panel, "open_message_panel", AsyncMock(return_value=(editor_page, editor))
    )
    submit = AsyncMock(return_value=_result())
    monkeypatch.setattr(SubmitFlow, "fill_and_submit", submit)
    request = InteractionExecutionRequest(
        interaction_type="creator_message", aweme_id="123", content="测试私信"
    )

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回预置端口。"""
        return api

    asyncio.run(
        executor.execute(
            spec=_spec(), request=request, api_factory=_factory, step_callback=callback
        )
    )

    assert api.resolved_aweme_ids == ["123"]
    open_creator.assert_awaited_once_with(page, "author-sec-id")
    assert submit.await_args.args[0] is editor_page
    assert submit.await_args.args[1] is editor
    assert submit.await_args.kwargs == {"require_explicit_submit": True}
    assert "creator_profile_opened" in [
        call.args[1] for call in callback.await_args_list
    ]


def test_message_creator_aborts_when_the_author_cannot_be_resolved(
    monkeypatch: pytest.MonkeyPatch, executor: DouyinInteractionExecutor
) -> None:
    """解析不出作者 sec_uid 时判 target_not_found（终态），不打开主页。"""
    page = _fake_page()
    _install_session(monkeypatch, page)
    api = FakeInteractionApi(sec_uid=None)
    open_creator = AsyncMock()
    monkeypatch.setattr(navigation, "open_creator_profile", open_creator)
    request = InteractionExecutionRequest(
        interaction_type="creator_message", aweme_id="123", content="测试私信"
    )

    async def _factory(_browser_page: object) -> FakeInteractionApi:
        """返回无法解析作者的端口。"""
        return api

    with pytest.raises(InteractionExecutionError) as captured:
        asyncio.run(
            executor.execute(spec=_spec(), request=request, api_factory=_factory)
        )

    assert captured.value.code == "target_not_found"
    assert captured.value.retryable is False
    open_creator.assert_not_awaited()
    assert api.aclose_calls == 1
