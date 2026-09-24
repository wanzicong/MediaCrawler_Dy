"""抖音 Web 签名模块的环境兜底测试。"""

import importlib
import os
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="PATHEXT 兜底只在 Windows 上生效")
def test_signing_defaults_pathext_before_importing_execjs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证缺少 PATHEXT 时签名模块会补上默认后缀列表。

    PyExecJS 在 Windows 上依靠 PATHEXT 把 ``node`` 补全成 ``node.EXE`` 才能定位运行时；
    IDE 任务、服务包装脚本等启动器可能不继承该变量，缺失时签名会整体报
    「Could not find an available JavaScript runtime」，让所有需要签名的接口失败。
    """
    monkeypatch.delenv("PATHEXT", raising=False)

    module = importlib.import_module("crawler.douyin_client.signing.a_bogus")
    importlib.reload(module)

    assert os.environ.get("PATHEXT")
