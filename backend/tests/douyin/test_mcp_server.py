import asyncio
from unittest.mock import AsyncMock

import pytest

from app.mcp_server import server


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
            "limit": 20,
            "skip": 40,
        },
    )
    assert result == {"data": [], "count": 0}


def test_mcp_keyword_tools_forward_safe_asset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"data": [], "count": 0})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server.list_douyin_keywords(
            search="FastAPI", status="crawled", limit=20, skip=5
        )
    )
    request.assert_awaited_once_with(
        "GET",
        "/douyin/keywords/",
        params={
            "search": "FastAPI",
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
            "mode": "combined",
            "max_awemes": 30,
            "fetch_comments": False,
            "account_pool_id": "pool-1",
        },
    )
