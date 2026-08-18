import asyncio
import logging
import traceback
from unittest.mock import AsyncMock

import httpx
import pytest
from crawler.bootstrap.logging import configure_sensitive_transport_logging
from crawler.douyin_client.client import DouyinClient
from crawler.douyin_client.errors import DataFetchError
from crawler.douyin_client.privacy import (
    anonymize_account_id,
    anonymize_user_id,
    map_aweme,
    map_comment,
    mask_nickname,
)


def test_sensitive_transport_loggers_do_not_emit_signed_urls_at_info() -> None:
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    previous_levels = (httpx_logger.level, httpcore_logger.level)
    try:
        httpx_logger.setLevel(logging.INFO)
        httpcore_logger.setLevel(logging.DEBUG)

        configure_sensitive_transport_logging()

        assert httpx_logger.level == logging.WARNING
        assert httpcore_logger.level == logging.WARNING
    finally:
        httpx_logger.setLevel(previous_levels[0])
        httpcore_logger.setLevel(previous_levels[1])


def test_douyin_http_error_traceback_does_not_expose_signed_url() -> None:
    request = httpx.Request(
        "GET",
        "https://www.douyin.com/aweme/detail?msToken=secret&a_bogus=signed",
    )
    response = httpx.Response(403, request=request)
    client = object.__new__(DouyinClient)
    client.http = AsyncMock()
    client.http.request.return_value = response

    with pytest.raises(DataFetchError) as captured:
        asyncio.run(client.request("GET", str(request.url)))

    rendered = "".join(
        traceback.format_exception(captured.type, captured.value, captured.tb)
    )
    assert "msToken" not in rendered
    assert "a_bogus" not in rendered
    assert "secret" not in rendered


def test_aweme_mapping_anonymizes_user_and_keeps_media_urls() -> None:
    mapped = map_aweme(
        {
            "aweme_id": "123",
            "aweme_type": 4,
            "desc": "中文标题",
            "create_time": 123456,
            "author": {
                "uid": "raw-user-id",
                "sec_uid": "sec-user-id",
                "nickname": "张三丰",
            },
            "statistics": {
                "digg_count": 10,
                "collect_count": 2,
                "comment_count": 3,
                "share_count": 4,
            },
            "video": {
                "raw_cover": {"url_list": ["cover-a", "cover-b"]},
                "play_addr": {"url_list": ["video-a", "video-b"]},
            },
            "music": {"play_url": {"uri": "music-url"}},
        },
        "关键词",
    )

    assert mapped["creator_hash"] == anonymize_user_id("raw-user-id")
    assert "raw-user-id" not in mapped.values()
    assert mapped["sec_uid"] == anonymize_user_id("sec-user-id")
    assert "sec-user-id" not in mapped.values()
    assert mapped["nickname"] == "张***丰"
    assert mapped["cover_url"] == "cover-b"
    assert mapped["video_download_url"] == "video-b"
    assert mapped["source_keyword"] == "关键词"


def test_comment_mapping_rejects_wrong_aweme_and_masks_nickname() -> None:
    comment = {
        "aweme_id": "123",
        "cid": "comment-1",
        "text": "评论内容",
        "user": {"uid": "raw", "sec_uid": "raw-sec-uid", "nickname": "李雷"},
    }

    assert map_comment(comment, "other") is None
    mapped = map_comment(comment, "123")
    assert mapped is not None
    assert mapped["nickname"] == "李*"
    assert mapped["creator_hash"] == anonymize_user_id("raw")
    assert mapped["sec_uid"] == anonymize_user_id("raw-sec-uid")
    assert "raw-sec-uid" not in mapped.values()


def test_account_hmac_is_stable_and_keyed() -> None:
    first = anonymize_account_id("dy:sec_uid:abc", "key-one")
    second = anonymize_account_id("dy:sec_uid:abc", "key-one")
    other_key = anonymize_account_id("dy:sec_uid:abc", "key-two")

    assert first == second
    assert first != other_key
    assert "abc" not in first
    assert mask_nickname("") == ""
