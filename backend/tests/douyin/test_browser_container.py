from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_browser_image_is_cdp_only_and_has_healthcheck() -> None:
    dockerfile = (ROOT / "docker/browser/Dockerfile").read_text(encoding="utf-8")
    supervisor = (ROOT / "docker/browser/supervisord.conf").read_text(
        encoding="utf-8"
    )

    assert "remote-debugging-port=9223" in supervisor
    assert "TCP-LISTEN:9222" in supervisor
    assert "/json/version" in dockerfile
    assert "playwright install" not in dockerfile
    assert "launch_persistent_context" not in dockerfile + supervisor


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
    assert "mc\", \"ready\", \"local" in compose
    assert "MINIO_ENDPOINT: minio:9000" in compose
    assert '"0.0.0.0:9100:9000"' not in compose
