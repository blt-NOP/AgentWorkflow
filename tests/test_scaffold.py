from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import PROJECT_ROOT, load_settings
from backend.app.main import create_app


@pytest.fixture
def settings(monkeypatch, tmp_path):
    for name in (
        "MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY", "MODEL_TIMEOUT_SECONDS",
        "AGENT_MAX_STEPS", "TOOL_TIMEOUT_SECONDS", "DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    return load_settings(tmp_path / "missing.env")


def test_health_and_frontend_do_not_expose_secret(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_API_KEY", "test-private-secret")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.invalid/v1")
    configured = load_settings(tmp_path / "missing.env")
    assert "test-private-secret" not in repr(configured)
    with TestClient(create_app(configured)) as client:
        response = client.get("/api/health")
        assert response.json() == {"status": "ok", "stage": "scaffold", "model_configured": True}
        for path in ("/api/health", "/", "/static/app.js", "/static/styles.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert "test-private-secret" not in response.text
        assert client.get("/.env").status_code == 404


def test_defaults_and_project_relative_path(settings):
    assert not settings.model_configured
    assert settings.data_dir == (PROJECT_ROOT / "data").resolve()


def test_environment_takes_precedence_over_dotenv(settings, monkeypatch, tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("MODEL_NAME=from-file\nMODEL_API_KEY=file-secret\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_NAME", "from-environment")
    loaded = load_settings(env_file)
    assert loaded.model_name == "from-environment"
    assert loaded.model_api_key == "file-secret"
    # load_dotenv writes file-only values to the process environment.
    monkeypatch.delenv("MODEL_API_KEY")


def test_invalid_step_limit_is_rejected(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MAX_STEPS", "0")
    with pytest.raises(ValueError, match="AGENT_MAX_STEPS"):
        load_settings(tmp_path / "missing.env")


def test_chat_is_explicitly_unimplemented_and_validates_input(settings):
    with TestClient(create_app(settings)) as client:
        session_id = str(uuid4())
        response = client.post("/api/chat", json={"session_id": session_id, "message": "讨论研究方向"})
        assert response.status_code == 501
        assert response.json()["detail"]["code"] == "AGENT_NOT_IMPLEMENTED"
        assert response.json()["detail"]["session_id"] == session_id
        for message in ("", "   ", "x" * 10001):
            assert client.post("/api/chat", json={"session_id": session_id, "message": message}).status_code == 422
        assert client.post("/api/chat", json={"session_id": "invalid", "message": "test"}).status_code == 422
