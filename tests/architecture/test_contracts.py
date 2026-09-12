"""跨模块契约的结构化一致性门禁（规格 §5 的 G14/G15）。

这里钉的是两份「互不 import 的平行声明」之间的一致性：

- G14：`crawler.browser.page.handle.PlaywrightPageHandle` 必须结构化满足
  `crawler.douyin_client.session.context.SessionContext`。browser 与 douyin_client
  互不 import（G1/G2），二者只靠 Protocol 的结构化匹配对齐；一旦有一侧改了方法名
  或签名，这里就会变红。
- G15：指纹键表在两侧各声明一份（browser 侧 `DOUYIN_FINGERPRINT_KEYS`、
  douyin_client 侧 `DouyinClient.FINGERPRINT_KEYS`），键名漂移由集合相等兜底。

两个判定都写成「对显式输入求问题列表」的纯函数，便于用合成反例证明规则不是空断言。
"""

from __future__ import annotations

from collections.abc import Sequence


def _structural_protocol_problems(
    implementation: object, protocol: object, *, expected_methods: Sequence[str]
) -> list[str]:
    """返回 implementation 未结构化满足 protocol 的明细（G14）。"""
    problems: list[str] = []
    if not getattr(protocol, "_is_runtime_protocol", False):
        problems.append(f"{protocol!r} 缺少 @runtime_checkable，无法做结构化一致性断言")
    for name in expected_methods:
        if not hasattr(implementation, name):
            problems.append(f"{implementation!r} 缺少方法 {name}()")
    if not isinstance(implementation, protocol):  # type: ignore[arg-type]
        problems.append(
            f"{implementation!r} 未结构化满足 {protocol!r}（签名或方法集不一致）"
        )
    return problems


def _fingerprint_key_problems(
    browser_keys: tuple[str, ...], client_keys: tuple[str, ...]
) -> list[str]:
    """返回两份指纹键表不一致的明细（G15）。"""
    problems: list[str] = []
    if not isinstance(browser_keys, tuple) or not all(
        isinstance(key, str) for key in browser_keys
    ):
        problems.append(f"browser 侧键表必须是 tuple[str, ...]：{browser_keys!r}")
    if not isinstance(client_keys, tuple) or not all(
        isinstance(key, str) for key in client_keys
    ):
        problems.append(f"douyin_client 侧键表必须是 tuple[str, ...]：{client_keys!r}")
    if not browser_keys:
        problems.append("browser 侧指纹键表为空：规则会空转")
    if not client_keys:
        problems.append("douyin_client 侧指纹键表为空：规则会空转")
    only_browser = sorted(set(browser_keys) - set(client_keys))
    only_client = sorted(set(client_keys) - set(browser_keys))
    if only_browser:
        problems.append(f"仅 browser 声明的键：{only_browser}")
    if only_client:
        problems.append(f"仅 douyin_client 声明的键：{only_client}")
    return problems


def test_browser_page_structurally_satisfies_session_context() -> None:
    """G14：PlaywrightPageHandle 必须结构化满足 douyin_client 的 SessionContext。"""
    from crawler.browser.page.handle import PlaywrightPageHandle
    from crawler.douyin_client.session.context import SessionContext

    problems = _structural_protocol_problems(
        PlaywrightPageHandle,
        SessionContext,
        expected_methods=("user_agent", "local_storage", "cookies", "fingerprint"),
    )
    assert not problems, (
        "browser 的页面句柄与 douyin_client 的入站契约必须结构一致（两侧均 @runtime_checkable）："
        f"{problems}"
    )


def test_fingerprint_key_sets_are_identical() -> None:
    """G15：browser 与 douyin_client 的指纹键表集合相等且都是 tuple[str, ...]。"""
    from crawler.browser.session.environment import DOUYIN_FINGERPRINT_KEYS
    from crawler.douyin_client.http.client import DouyinClient

    problems = _fingerprint_key_problems(
        DOUYIN_FINGERPRINT_KEYS, DouyinClient.FINGERPRINT_KEYS
    )
    assert not problems, (
        f"指纹键表出现漂移（缺键即不写入，但键名不允许漂移）：{problems}"
    )
