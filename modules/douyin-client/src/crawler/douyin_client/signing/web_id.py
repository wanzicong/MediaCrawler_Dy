# Portions adapted from MediaCrawler under NON-COMMERCIAL LEARNING LICENSE 1.1.

"""抖音 Web 端 webid 请求参数生成。"""

import random


def get_web_id() -> str:
    """生成抖音 Web 端请求参数 webid（19 位随机标识，模拟浏览器指纹）。"""

    def encode(value: int | None) -> str:
        if value is not None:
            return str(value ^ (int(16 * random.random()) >> (value // 4)))
        return f"{int(1e7)}-{int(1e3)}-{int(4e3)}-{int(8e3)}-{int(1e11)}"

    raw = "".join(encode(int(char)) if char in "018" else char for char in encode(None))
    return raw.replace("-", "")[:19]


__all__ = ["get_web_id"]
