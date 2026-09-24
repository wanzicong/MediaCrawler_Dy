# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 a_bogus 签名计算（execjs + 内置 ``resources/douyin.js``）。"""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注
    import execjs  # type: ignore[import-untyped]

# Windows 上 PyExecJS 依靠 PATHEXT 把 ``node`` 补全成 ``node.EXE`` 才能定位运行时；
# IDE 任务、服务包装脚本、容器/CI 等启动器可能继承不到 PATHEXT，此时签名会报
# 「Could not find an available JavaScript runtime」并让所有需要签名的接口失败。
# 缺省值必须在导入 execjs 之前补上，所以 execjs 改为在 _signer() 内惰性导入。
if sys.platform == "win32" and not os.environ.get("PATHEXT"):
    os.environ["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"


@lru_cache(maxsize=1)
def _signer() -> "execjs.ExternalRuntime.Context":
    """加载并编译内置 douyin.js 签名脚本，进程内只编译一次。"""
    import execjs  # noqa: PLC0415 - 必须在补齐 PATHEXT 之后再导入

    script_path = Path(__file__).resolve().parents[1] / "resources" / "douyin.js"
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


__all__ = ["get_a_bogus"]
