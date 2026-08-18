"""Alembic 迁移环境配置：离线/在线两种模式下执行数据库迁移。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 这是 Alembic 的 Config 对象，通过它可以访问
# 当前使用的 .ini 配置文件中的各项配置值
config = context.config

# 解析配置文件并初始化 Python 日志；
# 这一行基本完成各 logger 的配置
fileConfig(config.config_file_name)

# 在此添加模型的 MetaData 对象
# 以支持 'autogenerate'（自动生成迁移脚本）
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None

from crawler.bootstrap.settings import settings  # noqa
from crawler.business.model_registry import metadata  # noqa: E402

target_metadata = metadata

# 配置中的其他值可按 env.py 的需要获取：
# my_important_option = config.get_main_option("my_important_option")
# ... 等等


def get_url():
    """返回从应用配置构建的数据库连接 URL。"""
    return str(settings.SQLALCHEMY_DATABASE_URI)


def run_migrations_offline():
    """以“离线”模式执行迁移。

    此模式下仅使用 URL 配置上下文而不创建 Engine
    （当然这里传入 Engine 也是可以的）。由于跳过了 Engine 的创建，
    甚至不需要 DBAPI 可用即可运行。

    这里对 context.execute() 的调用会把给定的 SQL 字符串
    输出到迁移脚本中，而不是真正执行。

    """
    url = get_url()
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """以“在线”模式执行迁移。

    此模式下需要创建 Engine，并把一个数据库连接
    关联到迁移上下文中。

    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
