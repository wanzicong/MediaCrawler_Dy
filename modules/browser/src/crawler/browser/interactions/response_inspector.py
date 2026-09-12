# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""评论/私信发布响应的无状态解析（纯静态工具）。

集中发布请求/响应识别、平台状态码、错误文案与结果 id 提取等判定；
被 ``page_controller``（提交触发）与 ``submit_flow``（发送确认）复用。
方法已全部去掉下划线：它们是本包与 ``tests/browser/`` 的协作面，不是私有实现。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs


class ResponseInspector:
    """抖音互动网络响应的无状态解析器。

    所有方法均为静态方法：只依赖传入的 request/response/payload，不持有状态，
    便于被其他协作类与测试直接复用。
    """

    @staticmethod
    async def safe_json(response: Any) -> dict[str, Any]:
        """尽力解析响应 JSON，解析失败或非对象时返回空字典。"""
        try:
            payload = await response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def is_comment_publish_response(response: Any) -> bool:
        """判断响应是否来自抖音（新旧版）评论发布接口。"""
        try:
            return ResponseInspector.is_comment_publish_request(response.request)
        except Exception:
            return False

    @staticmethod
    def request_targets_reply(
        request: Any,
        *,
        target_comment_id: str,
        parent_comment_id: str | None,
    ) -> bool:
        """核验评论发布请求确实绑定到了已确认的目标评论（含二级回复场景）。"""
        try:
            post_data = str(request.post_data or "")
            fields: dict[str, list[str]] = parse_qs(post_data, keep_blank_values=True)
        except Exception:
            return False
        reply_id = (fields.get("reply_id") or [""])[0]
        reply_to_reply_id = (fields.get("reply_to_reply_id") or [""])[0]
        if parent_comment_id not in {None, "", "0"}:
            return (
                reply_id == parent_comment_id and reply_to_reply_id == target_comment_id
            )
        return reply_id == target_comment_id and reply_to_reply_id in {"", "0"}

    @staticmethod
    def is_comment_publish_request(request: Any) -> bool:
        """判断请求是否为评论发布请求（POST 且路径含 comment 与 publish/create/post）。"""
        try:
            if request.method != "POST":
                return False
            path = request.url.split("?", 1)[0].lower()
        except Exception:
            return False
        return "comment" in path and any(
            marker in path for marker in ("publish", "create", "post")
        )

    @staticmethod
    def result_id(payload: dict[str, Any]) -> str | None:
        """从平台响应中提取评论 ID（cid/comment_id，兼容多层包裹），未找到返回 None。"""
        for candidate in (payload, payload.get("data"), payload.get("result")):
            if not isinstance(candidate, dict):
                continue
            nested = candidate.get("comment")
            if isinstance(nested, dict):
                value = nested.get("cid") or nested.get("comment_id")
                if value:
                    return str(value)
            value = candidate.get("cid") or candidate.get("comment_id")
            if value:
                return str(value)
        return None

    @staticmethod
    def platform_status_code(payload: dict[str, Any]) -> object | None:
        """从（新旧版包裹的）响应中读取抖音业务状态码，找不到返回 None。"""
        for candidate in (
            payload,
            payload.get("data"),
            payload.get("result"),
        ):
            if isinstance(candidate, dict) and "status_code" in candidate:
                return candidate.get("status_code")
        return None

    @staticmethod
    def platform_error_message(payload: dict[str, Any], *, prefix: str) -> str:
        """从响应中提取平台错误文案并拼接前缀，未找到时仅返回前缀。"""
        for candidate in (payload, payload.get("data"), payload.get("result")):
            if not isinstance(candidate, dict):
                continue
            for key in ("status_msg", "message", "description"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return f"{prefix}：{value.strip()}"
        return prefix


__all__ = ["ResponseInspector"]
