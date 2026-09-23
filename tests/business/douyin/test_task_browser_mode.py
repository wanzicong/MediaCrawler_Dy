"""任务浏览器模式归一化的回归测试（临时浏览器登录任务曾整批失败）。"""

from crawler.business.douyin.accounts.models import DouyinBrowserMode
from crawler.business.douyin.tasks.crawler import session_browser_mode


def test_session_browser_mode_uses_enum_value_not_member_name() -> None:
    """验证枚举成员被归一化成取值，而不是 ``DouyinBrowserMode.local`` 这样的成员名。

    背景：Python 3.11 起 ``str(DouyinBrowserMode.local)`` 返回成员名，未绑定账号的
    「临时浏览器登录」任务因此在构造 CDP 会话时抛
    ``'DouyinBrowserMode.local' is not a valid BrowserMode``，全部失败。
    """
    assert session_browser_mode(DouyinBrowserMode.local, "remote") == "local"
    assert session_browser_mode(DouyinBrowserMode.remote, "local") == "remote"
    # 请求里已经是字符串（或来自历史数据）时保持原样
    assert session_browser_mode("local", "remote") == "local"
    assert session_browser_mode("remote", "local") == "remote"
    # 未指定时用服务端默认值，并且同样只取取值
    assert session_browser_mode(None, "local") == "local"
    assert session_browser_mode(None, "remote") == "remote"
