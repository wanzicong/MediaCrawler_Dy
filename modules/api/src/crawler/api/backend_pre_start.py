"""后端服务启动前的数据库就绪探测脚本：带重试地等待数据库可连接后再放行启动流程。"""

import logging

from crawler.bootstrap.database import engine
from sqlalchemy import Engine
from sqlmodel import Session, select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 最长重试 5 分钟
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init(db_engine: Engine) -> None:
    """尝试建立数据库会话以确认数据库已就绪，失败则抛出异常交给 tenacity 重试。

    参数：
        db_engine: 用于探测的数据库 Engine。
    """
    try:
        with Session(db_engine) as session:
            # 尝试创建会话，检查数据库是否已就绪
            session.exec(select(1))
    except Exception as e:
        logger.error(e)
        raise e


def main() -> None:
    """脚本入口：对默认 engine 执行数据库就绪探测。"""
    logger.info("Initializing service")
    init(engine)
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
