import re

import config as app_config

from app import _upgrade_database_to_head, create_app
from app.extensions import db


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, "CSRF token should be rendered explicitly in POST forms"
    return match.group(1)


def _make_prod_like_app(tmp_path, monkeypatch, **overrides):
    db_path = tmp_path / "security.sqlite"
    monkeypatch.setattr(
        app_config.ProdConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{db_path.as_posix()}",
    )
    monkeypatch.setattr(app_config.ProdConfig, "SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(
        app_config.ProdConfig,
        "AI_AGENT_API_KEY_ENCRYPTION_KEY",
        "test-ai-agent-encryption-key",
    )
    monkeypatch.setattr(app_config.ProdConfig, "WTF_CSRF_ENABLED", True)
    monkeypatch.setattr(app_config.ProdConfig, "RATELIMIT_ENABLED", True)
    monkeypatch.setattr(app_config.ProdConfig, "REQUIRE_DB_AT_HEAD", False)

    for key, value in overrides.items():
        monkeypatch.setattr(app_config.ProdConfig, key, value)

    app = create_app("prod")
    with app.app_context():
        _upgrade_database_to_head(app)
    return app


def test_post_forms_include_csrf_input(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b'name="csrf_token"' in response.data


def test_healthz_reports_version(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["status"] == "healthy"
    assert payload["version"]


def test_csrf_missing_token_is_rejected(tmp_path, monkeypatch):
    app = _make_prod_like_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.post(
        "/auth/register",
        data={
            "username": "secure-user",
            "password": "pw123456",
            "password2": "pw123456",
        },
    )
    assert response.status_code == 400
    assert "请求校验失败".encode("utf-8") in response.data


def test_csrf_valid_token_allows_registration(tmp_path, monkeypatch):
    app = _make_prod_like_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.get("/auth/register")
    token = _extract_csrf_token(response.get_data(as_text=True))

    register_response = client.post(
        "/auth/register",
        data={
            "username": "secure-user",
            "password": "pw123456",
            "password2": "pw123456",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert register_response.status_code == 302


def test_login_rate_limit_is_scoped_by_username(tmp_path, monkeypatch):
    app = _make_prod_like_app(
        tmp_path,
        monkeypatch,
        WTF_CSRF_ENABLED=False,
        LOGIN_RATE_LIMIT="2 per minute",
    )
    client = app.test_client()

    for _ in range(2):
        response = client.post(
            "/auth/login",
            data={"username": "alpha", "password": "wrong-password"},
        )
        assert response.status_code == 401

    limited = client.post(
        "/auth/login",
        data={"username": "alpha", "password": "wrong-password"},
    )
    assert limited.status_code == 429

    other_username = client.post(
        "/auth/login",
        data={"username": "beta", "password": "wrong-password"},
    )
    assert other_username.status_code == 401
