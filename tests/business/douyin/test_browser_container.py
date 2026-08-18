"""浏览器容器与对象存储容器配置的测试：以静态断言方式校验 docker 配置（Dockerfile、supervisord、compose、策略文件）符合 CDP 远程调试与安全基线要求。"""

import json
from pathlib import Path

ROOT = Path(__file__).parents[3]  # 仓库根目录（tests/business/douyin/ 上溯三级）


def test_browser_image_is_cdp_only_and_has_healthcheck() -> None:
    """验证浏览器镜像仅通过 CDP 暴露调试端口、具备健康检查，且未残留 playwright 直连启动方式。"""
    dockerfile = (ROOT / "docker/browser/Dockerfile").read_text(encoding="utf-8")
    supervisor = (ROOT / "docker/browser/supervisord.conf").read_text(encoding="utf-8")
    launcher = (ROOT / "docker/browser/start-chrome.sh").read_text(encoding="utf-8")

    assert "start-douyin-chrome" in supervisor
    assert "remote-debugging-port=9223" in launcher
    assert "--no-proxy-server" in launcher
    assert "--disable-infobars" in launcher
    assert "--disable-session-crashed-bubble" in launcher
    assert "--disable-save-password-bubble" in launcher
    assert "SingletonLock" in launcher
    assert "TCP-LISTEN:9222" in supervisor
    assert "/json/version" in dockerfile
    assert "playwright install" not in dockerfile
    assert "launch_persistent_context" not in dockerfile + supervisor + launcher


def test_browser_policy_blocks_douyin_external_protocol_prompts() -> None:
    """验证浏览器策略文件已屏蔽抖音外链协议唤起提示，并关闭通知、密码管理与自动填充。"""
    policy = json.loads(
        (ROOT / "docker/browser/policies.json").read_text(encoding="utf-8")
    )

    assert "bitbrowser:*" in policy["URLBlocklist"]
    assert "snssdk1128:*" in policy["URLBlocklist"]
    assert "xdg-open:*" not in policy["URLBlocklist"]
    assert policy["DefaultNotificationsSetting"] == 2
    assert policy["PasswordManagerEnabled"] is False
    assert policy["AutofillAddressEnabled"] is False
    assert policy["AutofillCreditCardEnabled"] is False


def test_browser_compose_ports_are_loopback_only() -> None:
    """验证浏览器 compose 端口仅绑定回环地址（127.0.0.1），且依赖方等待健康检查通过后再启动。"""
    compose = (ROOT / "compose.browser.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:9223:9222"' in compose
    assert '"127.0.0.1:6081:6080"' in compose
    assert "condition: service_healthy" in compose
    assert '"0.0.0.0:9223:9222"' not in compose


def test_minio_compose_is_persistent_healthy_and_loopback_only() -> None:
    """验证 MinIO compose 配置了数据持久化卷、就绪健康检查，且端口仅绑定回环地址。"""
    compose = (ROOT / "compose.storage.yml").read_text(encoding="utf-8")

    assert "minio-data:/data" in compose
    assert '"127.0.0.1:9100:9000"' in compose
    assert '"127.0.0.1:9101:9001"' in compose
    assert 'mc", "ready", "local' in compose
    assert "MINIO_ENDPOINT: minio:9000" in compose
    assert '"0.0.0.0:9100:9000"' not in compose
