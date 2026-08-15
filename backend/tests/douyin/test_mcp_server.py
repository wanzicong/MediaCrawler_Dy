import asyncio
from unittest.mock import AsyncMock

import pytest

from app.mcp_server import server


def test_mcp_task_tools_forward_track_filter_and_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(
        side_effect=[
            {"id": "task-1", "track_id": "track-1"},
            {"data": [], "count": 0},
        ]
    )
    monkeypatch.setattr(server.api, "request", request)

    asyncio.run(
        server.create_douyin_task(
            "search",
            ["FastAPI"],
            track_id="track-1",
            fetch_comments=False,
        )
    )
    asyncio.run(server.list_douyin_tasks(track_id="track-1", limit=10, skip=20))

    create_call = request.await_args_list[0]
    assert create_call.args == ("POST", "/douyin/tasks")
    assert create_call.kwargs["json_body"]["track_id"] == "track-1"
    assert create_call.kwargs["json_body"]["keywords"] == ["FastAPI"]
    assert request.await_args_list[1].args == ("GET", "/douyin/tasks")
    assert request.await_args_list[1].kwargs == {
        "params": {"limit": 10, "skip": 20, "track_id": "track-1"}
    }


def test_mcp_media_migration_forwards_only_task_and_asset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(
        return_value={"queued": 2, "skipped": 1, "message": "ok"}
    )
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server._request_douyin_media_migration("task-1", ["asset-1", "asset-2"])
    )

    request.assert_awaited_once_with(
        "POST",
        "/douyin/tasks/task-1/media/migrate-to-minio",
        json_body={"asset_ids": ["asset-1", "asset-2"]},
    )
    assert result["queued"] == 2
    assert not {
        "cookies",
        "token",
        "local_path",
        "minio_secret_key",
    }.intersection(request.await_args.kwargs["json_body"])


def test_mcp_unified_works_forwards_sort_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.list_douyin_works(
            "task-1",
            search="FastAPI",
            sort_by="liked_count",
            sort_order="desc",
            download_status="downloaded",
            subtitle_status="completed",
            tag_id="tag-1",
            limit=20,
            skip=40,
        )
    )

    request.assert_awaited_once_with(
        "GET",
        "/douyin/tasks/task-1/works",
        params={
            "search": "FastAPI",
            "sort_by": "liked_count",
            "sort_order": "desc",
            "download_status": "downloaded",
            "subtitle_status": "completed",
            "tag_id": "tag-1",
            "limit": 20,
            "skip": 40,
        },
    )
    assert result == {"data": [], "count": 0}


def test_mcp_comment_search_forwards_multidimensional_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0, "summary": {}})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.search_douyin_comments(
            comment_content="帐篷真的",
            search="帐篷",
            task_id="task-1",
            track_id="track-1",
            video_creator="露营作者",
            source_keyword="露营",
            comment_type="top_level",
            has_pictures="yes",
            min_likes=20,
            published_from=1_710_000_000,
            published_to=1_710_086_399,
            sort_by="like_count",
            limit=20,
            skip=40,
        )
    )

    request.assert_awaited_once_with(
        "GET",
        "/douyin/comments",
        params={
            "comment_content": "帐篷真的",
            "search": "帐篷",
            "task_id": "task-1",
            "track_id": "track-1",
            "video_creator": "露营作者",
            "source_keyword": "露营",
            "comment_type": "top_level",
            "has_pictures": "yes",
            "min_likes": 20,
            "published_from": 1_710_000_000,
            "published_to": 1_710_086_399,
            "sort_by": "like_count",
            "sort_order": "desc",
            "limit": 20,
            "skip": 40,
        },
    )
    assert result["count"] == 0


def test_mcp_tag_tools_forward_filters_and_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(
        side_effect=[
            {"data": [], "count": 0},
            {
                "aweme_count": 10,
                "tag_count": 3,
                "created_count": 1,
                "binding_count": 4,
            },
        ]
    )
    monkeypatch.setattr(server.api, "request", request)

    listed = asyncio.run(
        server.list_douyin_tags(
            search="FastAPI",
            task_id="task-1",
            track_id="track-1",
            limit=20,
            skip=5,
        )
    )
    synced = asyncio.run(server.sync_historical_douyin_tags())

    assert request.await_args_list[0].args == ("GET", "/douyin/tags/")
    assert request.await_args_list[0].kwargs == {
        "params": {
            "search": "FastAPI",
            "task_id": "task-1",
            "track_id": "track-1",
            "limit": 20,
            "skip": 5,
        }
    }
    assert request.await_args_list[1].args == ("POST", "/douyin/tags/sync")
    assert listed["count"] == 0
    assert synced["binding_count"] == 4


def test_mcp_keyword_tools_forward_safe_asset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.list_douyin_keywords(
            search="FastAPI",
            track_id="track-1",
            status="crawled",
            limit=20,
            skip=5,
        )
    )
    request.assert_awaited_once_with(
        "GET",
        "/douyin/keywords/",
        params={
            "search": "FastAPI",
            "track_id": "track-1",
            "status": "crawled",
            "limit": 20,
            "skip": 5,
        },
    )
    assert result["count"] == 0

    request.reset_mock()
    request.return_value = {"data": [], "count": 1}
    asyncio.run(
        server.create_douyin_keyword_tasks(
            ["keyword-1", "keyword-2"],
            track_id="track-1",
            mode="combined",
            max_awemes=30,
            fetch_comments=False,
            account_pool_id="pool-1",
        )
    )
    request.assert_awaited_once_with(
        "POST",
        "/douyin/keywords/batch-tasks",
        json_body={
            "keyword_ids": ["keyword-1", "keyword-2"],
            "track_id": "track-1",
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": False,
            "account_pool_id": "pool-1",
        },
    )


def test_mcp_track_tools_forward_product_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0})
    monkeypatch.setattr(server.api, "request", request)

    asyncio.run(server.list_douyin_tracks(search="露营", enabled=True))
    request.assert_awaited_once_with(
        "GET",
        "/douyin/tracks",
        params={"search": "露营", "enabled": True, "limit": 100, "skip": 0},
    )

    request.reset_mock()
    asyncio.run(
        server.create_douyin_track(
            "户外露营", ["帐篷", "露营炉具"], description="目标人群"
        )
    )
    request.assert_awaited_once_with(
        "POST",
        "/douyin/tracks",
        json_body={
            "name": "户外露营",
            "description": "目标人群",
            "keywords": ["帐篷", "露营炉具"],
        },
    )

    request.reset_mock()
    asyncio.run(server.run_douyin_track("track-1", account_pool_id="pool-1"))
    request.assert_awaited_once_with(
        "POST",
        "/douyin/tracks/track-1/tasks",
        json_body={
            "keyword_ids": [],
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": True,
            "max_comments_per_aweme": 10,
            "request_delay_level": "steady",
            "account_pool_id": "pool-1",
        },
    )

    request.reset_mock()
    asyncio.run(
        server.run_douyin_track(
            "track-1",
            account_pool_id="pool-1",
            keyword_ids=["keyword-1", "keyword-2"],
        )
    )
    request.assert_awaited_once_with(
        "POST",
        "/douyin/tracks/track-1/tasks",
        json_body={
            "keyword_ids": ["keyword-1", "keyword-2"],
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": True,
            "max_comments_per_aweme": 10,
            "request_delay_level": "steady",
            "account_pool_id": "pool-1",
        },
    )


def test_mcp_interaction_only_prepares_pending_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(
        side_effect=[
            {"allowed": True, "message": "ok"},
            {"id": "interaction-1", "status": "pending_confirmation"},
        ]
    )
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.prepare_douyin_interaction(
            task_id="task-1",
            aweme_id="aweme-1",
            account_id="account-1",
            interaction_type="comment_reply",
            content="人工确认后才发送",
            target_comment_id="comment-1",
        )
    )

    payload = {
        "task_id": "task-1",
        "aweme_id": "aweme-1",
        "account_id": "account-1",
        "interaction_type": "comment_reply",
        "content": "人工确认后才发送",
        "target_comment_id": "comment-1",
    }
    assert request.await_args_list[0].args == (
        "POST",
        "/douyin/interactions/preflight",
    )
    assert request.await_args_list[0].kwargs == {"json_body": payload}
    assert request.await_args_list[1].args == (
        "POST",
        "/douyin/interactions",
    )
    assert request.await_args_list[1].kwargs == {"json_body": payload}
    assert result["prepared"] is True
    assert result["interaction"]["status"] == "pending_confirmation"


def test_mcp_interaction_list_forwards_track_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.list_douyin_interactions(
            task_id="task-1",
            track_id="track-1",
            status="failed",
            limit=20,
            skip=5,
        )
    )

    request.assert_awaited_once_with(
        "GET",
        "/douyin/interactions",
        params={
            "limit": 20,
            "skip": 5,
            "task_id": "task-1",
            "track_id": "track-1",
            "status": "failed",
        },
    )
    assert result == {"data": [], "count": 0}


def test_mcp_interaction_has_no_direct_confirm_tool() -> None:
    assert not hasattr(server, "confirm_douyin_interaction")
