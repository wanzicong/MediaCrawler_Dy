# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 Web 端签名工具：webid 生成与 a_bogus 签名计算。

签名通过 execjs 调用内置的 resources/douyin.js 完成。
"""

import random
from functools import lru_cache
from pathlib import Path

import execjs  # type: ignore[import-untyped]


def get_web_id() -> str:
    """生成抖音 Web 端请求参数 webid（19 位随机标识，模拟浏览器指纹）。"""

    def encode(value: int | None) -> str:
        if value is not None:
            return str(value ^ (int(16 * random.random()) >> (value // 4)))
        return f"{int(1e7)}-{int(1e3)}-{int(4e3)}-{int(8e3)}-{int(1e11)}"

    raw = "".join(encode(int(char)) if char in "018" else char for char in encode(None))
    return raw.replace("-", "")[:19]


@lru_cache(maxsize=1)
def _signer() -> execjs.ExternalRuntime.Context:
    """加载并编译内置 douyin.js 签名脚本，进程内只编译一次。"""
    script_path = Path(__file__).with_name("resources") / "douyin.js"
    return execjs.compile(script_path.read_text(encoding="utf-8-sig"))


def get_a_bogus(uri: str, query_string: str, user_agent: str) -> str:
    """计算抖音接口的 a_bogus 签名参数。

    参数：
        uri: 请求路径，用于选择签名函数（包含 /reply 时使用 sign_reply，否则 sign_datail）。
        query_string: 已编码的查询字符串。
        user_agent: 请求使用的 User-Agent。

    返回：
        a_bogus 签名字符串。
    """
    function_name = "sign_reply" if "/reply" in uri else "sign_datail"
    return str(_signer().call(function_name, query_string, user_agent))
