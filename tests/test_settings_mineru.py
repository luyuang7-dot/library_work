from __future__ import annotations

from unittest.mock import patch

from app.extensions import db
from app.models import AIAgentSetting, User, UserSetting


def test_settings_page_initializes_user_setting(login_client, app):
    response = login_client.get("/settings/")
    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        settings = db.session.get(UserSetting, user.id)
        assert settings is not None
        assert settings.mineru_url


def test_save_mineru_url_and_change_password(login_client, app):
    save_response = login_client.post(
        "/settings/",
        data={"action": "mineru", "mineru_url": "http://127.0.0.1:9000"},
        follow_redirects=True,
    )
    assert save_response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        settings = db.session.get(UserSetting, user.id)
        assert settings.mineru_url == "http://127.0.0.1:9000"

    password_response = login_client.post(
        "/settings/",
        data={
            "action": "change_password",
            "current_password": "Password1!",
            "new_password": "Changed123!",
            "confirm_password": "Changed123!",
        },
        follow_redirects=False,
    )
    assert password_response.status_code == 302


@patch("app.blueprints.settings.mineru_client.health_check")
def test_test_mineru_endpoint(mock_health_check, login_client):
    mock_health_check.return_value = {"version": "3.2.0", "status": "ok", "queued_tasks": 0}
    response = login_client.post(
        "/settings/test_mineru",
        data={"mineru_url": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["version"] == "3.2.0"


def test_save_ai_journal_settings(login_client, app):
    with patch("app.services.ai_agent.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
        response = login_client.post(
            "/settings/",
            data={
                "action": "save_ai_journal",
                "agent_name": "TestAgent",
                "agent_enabled": "on",
                "ai_api_url": "https://api.example.test/v1/chat/completions",
                "ai_model": "demo-model",
                "user_preference": "简洁一点",
                "ai_api_key": "secret-key",
            },
            follow_redirects=True,
        )
    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        setting = db.session.get(AIAgentSetting, user.id)
        assert setting is not None
        assert setting.agent_name == "TestAgent"
        assert setting.enabled is True
        assert setting.api_url == "https://api.example.test/v1/chat/completions"
        assert setting.model == "demo-model"
        assert setting.user_preference == "简洁一点"
        assert setting.api_key == "secret-key"
