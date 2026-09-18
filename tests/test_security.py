from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twistd import config
from twistd.config import Settings, available_cpus
from twistd.cube import SOLVED
from twistd.main import create_app


def test_security_headers_on_api_responses(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["content-security-policy"].startswith("default-src 'none'")
    assert resp.headers["cache-control"] == "no-store"


def test_docs_get_a_csp_that_lets_them_render(client: TestClient) -> None:
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "cdn.jsdelivr.net" in resp.headers["content-security-policy"]


def test_oversized_body_rejected_by_content_length(client: TestClient) -> None:
    resp = client.post(
        "/solve",
        content=b'{"cube": "' + b"U" * 5000 + b'"}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"]


def test_oversized_streamed_body_rejected(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:  # no Content-Length: chunked transfer
        yield b'{"cube": "'
        for _ in range(50):
            yield b"U" * 100
        yield b'"}'

    resp = client.post("/solve", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code in (400, 413)


def test_long_cube_string_rejected_before_processing(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": "U" * 200})
    assert resp.status_code == 400
    assert "cube" in resp.json()["detail"]


def test_unknown_fields_rejected(client: TestClient) -> None:
    resp = client.post("/solve", json={"cube": SOLVED, "admin": True})
    assert resp.status_code == 400


def test_errors_do_not_echo_input(client: TestClient) -> None:
    probe = "<script>alert(1)</script>"
    resp = client.post("/solve", json={"cube": probe})
    assert resp.status_code == 400
    assert probe not in resp.text


def test_docs_can_be_disabled() -> None:
    app = create_app(Settings(docs_enabled=False, solver_threads=1))
    with TestClient(app) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404
        assert c.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("BATCHING", "sometimes"),
        ("MAX_PENDING", "0"),
        ("SOLVER_THREADS", "-1"),
        ("SOLVE_TIMEOUT_S", "0"),
    ],
)
def test_bad_config_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, env: str, value: str
) -> None:
    monkeypatch.setenv(env, value)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_cpu_detection_honors_cgroup_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_cgroup_cpu_quota", lambda: 1.5)
    assert available_cpus() <= 2
    monkeypatch.setattr(config, "_cgroup_cpu_quota", lambda: 0.25)
    assert available_cpus() == 1


def test_cgroup_v2_quota_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real_path = config.Path
    cpu_max = tmp_path / "cpu.max"

    def fake_path(p: str) -> Path:
        return cpu_max if p == "/sys/fs/cgroup/cpu.max" else real_path(tmp_path / "missing")

    monkeypatch.setattr(config, "Path", fake_path)
    cpu_max.write_text("200000 100000\n")
    assert config._cgroup_cpu_quota() == 2.0
    cpu_max.write_text("max 100000\n")
    assert config._cgroup_cpu_quota() is None
