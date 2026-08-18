"""后端启动前置检查脚本的测试：验证数据库连接探测逻辑在连接成功时的行为。"""

from unittest.mock import MagicMock, patch

from crawler.api.backend_pre_start import init, logger
from sqlmodel import select


def test_init_successful_connection() -> None:
    """验证数据库连接正常时 init 能成功执行探测查询且不抛异常。"""
    engine_mock = MagicMock()

    session_mock = MagicMock()
    session_mock.__enter__.return_value = session_mock

    select1 = select(1)

    with (
        patch("crawler.api.backend_pre_start.Session", return_value=session_mock),
        patch("crawler.api.backend_pre_start.select", return_value=select1),
        patch.object(logger, "info"),
        patch.object(logger, "error"),
        patch.object(logger, "warn"),
    ):
        try:
            init(engine_mock)
            connection_successful = True
        except Exception:
            connection_successful = False

        assert connection_successful, (
            "The database connection should be successful and not raise an exception."
        )

        session_mock.exec.assert_called_once_with(select1)
