from __future__ import annotations

from unittest.mock import patch

import config as app_config

from app import DatabaseMigrationRequired, create_app


def test_create_app_test_env_builds_without_runtime_bootstrap():
    app = create_app("test")
    assert app is not None


def test_create_app_prod_requires_non_default_secret(monkeypatch):
    monkeypatch.setattr(app_config.ProdConfig, "SECRET_KEY", app_config.DEFAULT_SECRET_KEY)
    monkeypatch.setattr(
        app_config.ProdConfig,
        "AI_AGENT_API_KEY_ENCRYPTION_KEY",
        "test-ai-agent-encryption-key",
    )
    monkeypatch.setattr(app_config.ProdConfig, "REQUIRE_DB_AT_HEAD", False)

    try:
        create_app("prod")
    except RuntimeError as exc:
        assert "FLASK_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("prod startup should fail with the default secret key")


def test_create_app_prod_requires_explicit_ai_encryption_key(monkeypatch):
    monkeypatch.setattr(app_config.ProdConfig, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(
        app_config.ProdConfig,
        "AI_AGENT_API_KEY_ENCRYPTION_KEY",
        app_config.DEFAULT_AI_AGENT_ENCRYPTION_KEY,
    )
    monkeypatch.setattr(app_config.ProdConfig, "REQUIRE_DB_AT_HEAD", False)

    try:
        create_app("prod")
    except RuntimeError as exc:
        assert "AI_AGENT_API_KEY_ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("prod startup should fail without an explicit AI key")


def test_create_app_prod_requires_database_at_head(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config.ProdConfig, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(
        app_config.ProdConfig,
        "AI_AGENT_API_KEY_ENCRYPTION_KEY",
        "test-ai-agent-encryption-key",
    )
    monkeypatch.setattr(
        app_config.ProdConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{(tmp_path / 'prod-needs-migration.sqlite').as_posix()}",
    )

    try:
        create_app("prod")
    except DatabaseMigrationRequired as exc:
        assert "latest Alembic revision" in str(exc)
    else:
        raise AssertionError("prod startup should fail when the database is not migrated")


def test_request_logging_adds_request_id_and_completion_log(client):
    with patch.object(client.application.logger, "info") as mocked:
        response = client.get("/healthz", headers={"X-Forwarded-For": "203.0.113.8"})

    request_id = response.headers.get("X-Request-ID")
    assert request_id
    mocked.assert_called()
    args = mocked.call_args.args
    assert "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s remote_addr=%s user_id=%s" in args[0]
    assert args[1] == request_id
    assert args[2] == "GET"
    assert args[3] == "/healthz"
    assert args[4] == 200
    assert args[6] == "203.0.113.8"


def test_request_logging_preserves_incoming_request_id(client):
    incoming_request_id = "req-from-proxy-123"

    with patch.object(client.application.logger, "info") as mocked:
        response = client.get("/healthz", headers={"X-Request-ID": incoming_request_id})

    assert response.headers.get("X-Request-ID") == incoming_request_id
    mocked.assert_called()
    assert mocked.call_args.args[1] == incoming_request_id
