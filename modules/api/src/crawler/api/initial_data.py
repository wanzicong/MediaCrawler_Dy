"""初始化数据脚本：服务首次部署时向数据库写入初始数据（如首个超级管理员）。"""

import logging

from crawler.bootstrap.database import engine
from crawler.business.identity.bootstrap import init_db
from sqlmodel import Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    """打开数据库会话并执行初始化数据的写入。"""
    with Session(engine) as session:
        init_db(session)


def main() -> None:
    """脚本入口：执行初始化数据写入。"""
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
