"""抖音互动响应解析测试（``ResponseInspector``）。

全部为无状态判定：发布请求/响应的识别、回复绑定关系核验、平台状态码与错误
文案提取、评论 id 的多层包裹解析；异常输入一律返回安全缺省值而不是抛出。
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from crawler.browser.interactions.response_inspector import ResponseInspector


def _request(
    *,
    method: str = "POST",
    url: str = "https://www.douyin.com/aweme/v1/web/comment/publish/?aid=6383",
    post_data: str = "",
) -> MagicMock:
    """构造一个发布请求替身。"""
    request = MagicMock()
    request.method = method
    request.url = url
    request.post_data = post_data
    return request


# ---- 发布请求/响应识别 ----


@pytest.mark.parametrize(
    "path",
    [
        "/aweme/v1/web/comment/publish/",
        "/aweme/v1/web/comment/create/",
        "/api/comment/post/",
    ],
)
def test_comment_publish_request_accepts_current_endpoint_variants(path: str) -> None:
    """评论发布接口的多种端点写法都被识别为发布请求。"""
    request = _request(url=f"https://www.douyin.com{path}?aid=6383")

    assert ResponseInspector.is_comment_publish_request(request) is True


def test_comment_publish_request_rejects_reads_and_other_methods() -> None:
    """GET 只读评论列表、以及非评论路径都不算发布请求。"""
    list_request = _request(
        method="GET", url="https://www.douyin.com/aweme/v1/web/comment/list/"
    )
    other_request = _request(url="https://www.douyin.com/aweme/v1/web/like/publish/")

    assert ResponseInspector.is_comment_publish_request(list_request) is False
    assert ResponseInspector.is_comment_publish_request(other_request) is False


def test_publish_response_inspection_never_leaks_on_broken_objects() -> None:
    """缺少 request 属性的对象按「非发布请求」处理，不向上抛异常。"""
    assert ResponseInspector.is_comment_publish_response(object()) is False
    assert ResponseInspector.is_comment_publish_request(object()) is False


def test_comment_publish_response_follows_the_wrapped_request() -> None:
    """响应识别委托给其 request：POST 评论发布为 True，只读列表为 False。"""
    publish = MagicMock()
    publish.request = _request()
    read = MagicMock()
    read.request = _request(method="GET", url="https://www.douyin.com/comment/list/")

    assert ResponseInspector.is_comment_publish_response(publish) is True
    assert ResponseInspector.is_comment_publish_response(read) is False


# ---- 回复绑定关系核验 ----


def test_top_level_reply_targets_the_confirmed_comment() -> None:
    """一级评论回复：reply_id 等于目标评论且 reply_to_reply_id 为空/0。"""
    request = _request(
        post_data="aweme_id=123&text=reply&reply_id=456&reply_to_reply_id=0"
    )

    assert (
        ResponseInspector.request_targets_reply(
            request, target_comment_id="456", parent_comment_id=None
        )
        is True
    )
    assert (
        ResponseInspector.request_targets_reply(
            request, target_comment_id="456", parent_comment_id="0"
        )
        is True
    )
    assert (
        ResponseInspector.request_targets_reply(
            request, target_comment_id="789", parent_comment_id="0"
        )
        is False
    )


def test_sub_comment_reply_requires_parent_and_child_binding() -> None:
    """二级评论回复：reply_id 必须是父评论、reply_to_reply_id 必须是目标子评论。"""
    request = _request(post_data="reply_id=parent-1&reply_to_reply_id=child-2")

    assert (
        ResponseInspector.request_targets_reply(
            request, target_comment_id="child-2", parent_comment_id="parent-1"
        )
        is True
    )
    assert (
        ResponseInspector.request_targets_reply(
            request, target_comment_id="child-9", parent_comment_id="parent-1"
        )
        is False
    )


def test_reply_binding_check_is_false_for_missing_or_broken_post_data() -> None:
    """缺 post_data 或对象不可解析时一律判为「未绑定」，不抛异常。"""
    assert (
        ResponseInspector.request_targets_reply(
            _request(), target_comment_id="456", parent_comment_id=None
        )
        is False
    )
    assert (
        ResponseInspector.request_targets_reply(
            object(), target_comment_id="456", parent_comment_id=None
        )
        is False
    )


# ---- 平台状态码 / 错误文案 / 结果 id ----


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"status_code": 0}, 0),
        ({"status_code": "0"}, "0"),
        ({"data": {"status_code": 8}}, 8),
        ({"result": {"status_code": 0}}, 0),
        ({"data": {"comments": []}}, None),
        ({}, None),
    ],
)
def test_platform_status_code_reads_nested_payloads(
    payload: dict[str, Any], expected_status: object
) -> None:
    """业务状态码按 顶层/data/result 三层顺序读取，找不到返回 None。"""
    assert ResponseInspector.platform_status_code(payload) == expected_status


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status_code": 8, "status_msg": "评论发送失败"}, "抖音未接受：评论发送失败"),
        ({"data": {"message": "请求太频繁"}}, "抖音未接受：请求太频繁"),
        ({"result": {"description": "内容不合规"}}, "抖音未接受：内容不合规"),
        ({"data": {"status_msg": "   "}}, "抖音未接受"),
        ({}, "抖音未接受"),
    ],
)
def test_platform_error_message_prefers_the_first_available_text(
    payload: dict[str, Any], expected: str
) -> None:
    """错误文案按 status_msg/message/description 顺序提取，缺失时只留前缀。"""
    assert (
        ResponseInspector.platform_error_message(payload, prefix="抖音未接受")
        == expected
    )


@pytest.mark.parametrize(
    ("payload", "expected_platform_id"),
    [
        ({"status_code": 1}, None),
        ({"status_code": 0, "comment": {"cid": "cid-1"}}, "cid-1"),
        ({"status_code": 0, "comment": {"comment_id": "cid-2"}}, "cid-2"),
        ({"status_code": 0, "data": {"cid": "cid-3"}}, "cid-3"),
        ({"status_code": 0, "data": {"comment": {"cid": "cid-4"}}}, "cid-4"),
        ({"data": {"status_code": 0, "cid": "cid-5"}}, "cid-5"),
        ({"result": {"comment_id": "cid-6"}}, "cid-6"),
        ({"data": {"comment": "not-a-dict"}}, None),
    ],
)
def test_result_id_extracts_comment_id_from_every_wrapping(
    payload: dict[str, Any], expected_platform_id: str | None
) -> None:
    """评论 id 兼容 cid/comment_id 与多层包裹，缺失或形状不符时返回 None。"""
    assert ResponseInspector.result_id(payload) == expected_platform_id


# ---- 响应体解析 ----


def test_safe_json_returns_dict_and_swallows_broken_payloads() -> None:
    """响应体解析失败或不是对象时返回空字典。"""
    good = AsyncMock()
    good.json.return_value = {"status_code": 0}
    broken = AsyncMock()
    broken.json.side_effect = ValueError("not json")
    list_body = AsyncMock()
    list_body.json.return_value = [1, 2]

    assert asyncio.run(ResponseInspector.safe_json(good)) == {"status_code": 0}
    assert asyncio.run(ResponseInspector.safe_json(broken)) == {}
    assert asyncio.run(ResponseInspector.safe_json(list_body)) == {}
