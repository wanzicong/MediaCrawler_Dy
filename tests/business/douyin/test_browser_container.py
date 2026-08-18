import json
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_browser_image_is_cdp_only_and_has_healthcheck() -> None:
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
    compose = (ROOT / "compose.browser.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:9223:9222"' in compose
    assert '"127.0.0.1:6081:6080"' in compose
    assert "condition: service_healthy" in compose
    assert '"0.0.0.0:9223:9222"' not in compose


def test_minio_compose_is_persistent_healthy_and_loopback_only() -> None:
    compose = (ROOT / "compose.storage.yml").read_text(encoding="utf-8")

    assert "minio-data:/data" in compose
    assert '"127.0.0.1:9100:9000"' in compose
    assert '"127.0.0.1:9101:9001"' in compose
    assert 'mc", "ready", "local' in compose
    assert "MINIO_ENDPOINT: minio:9000" in compose
    assert '"0.0.0.0:9100:9000"' not in compose
