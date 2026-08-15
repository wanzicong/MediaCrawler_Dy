# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

import random
from functools import lru_cache
from pathlib import Path

import execjs  # type: ignore[import-untyped]


def get_web_id() -> str:
    def encode(value: int | None) -> str:
        if value is not None:
            return str(value ^ (int(16 * random.random()) >> (value // 4)))
        return f"{int(1e7)}-{int(1e3)}-{int(4e3)}-{int(8e3)}-{int(1e11)}"

    raw = "".join(encode(int(char)) if char in "018" else char for char in encode(None))
    return raw.replace("-", "")[:19]


@lru_cache(maxsize=1)
def _signer() -> execjs.ExternalRuntime.Context:
    script_path = Path(__file__).with_name("resources") / "douyin.js"
    return execjs.compile(script_path.read_text(encoding="utf-8-sig"))


def get_a_bogus(uri: str, query_string: str, user_agent: str) -> str:
    function_name = "sign_reply" if "/reply" in uri else "sign_datail"
    return str(_signer().call(function_name, query_string, user_agent))
