"""抖音 Web 端签名：webid 生成与 a_bogus 计算。"""

from crawler.douyin_client.signing.a_bogus import get_a_bogus as get_a_bogus
from crawler.douyin_client.signing.web_id import get_web_id as get_web_id

__all__ = ["get_a_bogus", "get_web_id"]
