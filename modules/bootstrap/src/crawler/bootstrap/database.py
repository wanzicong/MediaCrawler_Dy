"""共享 SQLAlchemy 引擎的构建。

数据库初始化（建表、创建初始用户）不放在本模块内，因为创建应用用户
属于身份领域行为，而非框架层职责。
"""

from crawler.bootstrap.settings import settings
from sqlmodel import create_engine

# 全局共享的数据库引擎，连接串来自 settings.SQLALCHEMY_DATABASE_URI
engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
