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
