from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from app.extensions import db
from app.models import AIAgentActivity, AIAgentJournal, AIAgentSetting, User
from app.services.ai_agent import (
    DEFAULT_DAILY_ROLLUP_MINUTE,
    _build_messages,
    format_daily_rollup_time,
    format_fixed_prune_time,
    generate_weekly_journal_from_recent_daily,
    get_or_create_setting,
    prune_previous_day_activities,
    record_activity,
    run_due_daily_rollups,
)


def _today_at(hour: int, minute: int):
    base = datetime.now().astimezone()
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _recent_sunday_at(hour: int, minute: int):
    base = _today_at(hour, minute)
    delta = (base.weekday() - 6) % 7
    return base - timedelta(days=delta)


def _patch_post(monkeypatch, response_body):
    calls = []

    class FakeResponse:
        text = ""
        is_redirect = False

        def raise_for_status(self):
            return None

        def json(self):
            return response_body

    def fake_post(url, json, headers, timeout, **kwargs):
        calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
                "kwargs": kwargs,
            }
        )
        return FakeResponse()

    from app.services import ai_agent as ai_agent_service

    monkeypatch.setattr(ai_agent_service.requests, "post", fake_post)
    return calls


def test_ai_agent_setting_and_activity_are_user_scoped(app):
    with app.app_context():
        u1 = User(username="agent_a", is_approved=True)
        u1.set_password("Password1!")
        u2 = User(username="agent_b", is_approved=True)
        u2.set_password("Password1!")
        db.session.add_all([u1, u2])
        db.session.commit()

        s1 = get_or_create_setting(u1.id)
        s2 = get_or_create_setting(u2.id)
        s1.agent_name = "Agent A"
        s2.agent_name = "Agent B"
        db.session.commit()

        record_activity(u1.id, "document_create", "Create A")
        record_activity(u2.id, "document_create", "Create B")

        assert db.session.get(AIAgentSetting, u1.id).agent_name == "Agent A"
        assert db.session.get(AIAgentSetting, u2.id).agent_name == "Agent B"
        assert AIAgentActivity.query.filter_by(user_id=u1.id).count() == 1
        assert AIAgentActivity.query.filter_by(user_id=u2.id).count() == 1


def test_ai_agent_state_requires_login(client):
    resp = client.get("/ai-agent/api/state")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_ai_agent_state_update_is_user_scoped(client, app):
    with app.app_context():
        user = User(username="alpha", email="alpha@example.com", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()
    client.post("/auth/login", data={"username": "alpha", "password": "Password1!"})
    resp = client.post(
        "/ai-agent/api/state",
        json={"agent_name": "Alpha", "user_preference": "少写抒情句"},
    )
    assert resp.status_code == 200
    state = resp.get_json()["state"]
    assert state["agent_name"] == "Alpha"
    assert state["daily_rollup_time"] == "23:59"

    client.post("/auth/logout")
    with app.app_context():
        user = User(username="beta", email="beta@example.com", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()
    client.post("/auth/login", data={"username": "beta", "password": "Password1!"})
    resp = client.get("/ai-agent/api/state")
    assert resp.status_code == 200
    assert resp.get_json()["state"]["agent_name"] != "Alpha"


def test_settings_save_ai_agent_config(login_client, app):
    with patch("app.services.ai_agent.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
        resp = login_client.post(
            "/settings/",
            data={
                "action": "save_ai_journal",
                "agent_name": "Logger",
                "agent_enabled": "on",
                "ai_api_url": "https://api.example.test/journal",
                "ai_model": "deepseek-chat",
                "user_preference": "突出重点",
                "ai_api_key": "sk-secret-value",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert b"sk-secret-value" not in resp.data

    with app.app_context():
        setting = AIAgentSetting.query.one()
        assert setting.agent_name == "Logger"
        assert setting.api_url == "https://api.example.test/journal"
        assert setting.api_key == "sk-secret-value"
        assert setting.model == "deepseek-chat"
        assert setting.user_preference == "突出重点"
        assert setting.daily_rollup_minute == DEFAULT_DAILY_ROLLUP_MINUTE


def test_rollup_time_helpers():
    assert format_daily_rollup_time(DEFAULT_DAILY_ROLLUP_MINUTE) == "23:59"
    assert format_fixed_prune_time() == "12:00"


def test_build_messages_includes_user_preference(app):
    with app.app_context():
        user = User(username="prompt_user", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.agent_name = "阿卷"
        setting.user_preference = "突出重点，少写抒情句。"
        db.session.commit()

        messages = _build_messages(setting, "today", [])

        assert "阿卷" in messages[0]["content"]
        assert "突出重点，少写抒情句。" in messages[0]["content"]


def test_daily_rollup_generation_at_2359(app, monkeypatch):
    with app.app_context():
        user = User(username="rollup_user", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.api_url = "https://api.deepseek.com/v1/chat/completions"
        setting.api_key = "sk-test"
        setting.model = "deepseek-chat"
        db.session.commit()

        rollup_time = _today_at(23, 59)
        for hour, label in ((9, "A"), (14, "B"), (22, "C")):
            db.session.add(
                AIAgentActivity(
                    user_id=user.id,
                    event_type="page_view",
                    label=label,
                    metadata_json="{}",
                    created_at=rollup_time.replace(hour=hour, minute=0).astimezone(),
                )
            )
        db.session.commit()

        calls = _patch_post(
            monkeypatch,
            {"choices": [{"message": {"role": "assistant", "content": "daily content"}}]},
        )

        result = run_due_daily_rollups(user.id, now=rollup_time)

        assert result[0]["ok"] is True
        assert result[0]["skipped"] is False
        assert result[1]["skipped"] is True
        assert result[1]["reason"] == "not_prune_time"

        journal = AIAgentJournal.query.filter_by(user_id=user.id, period="daily").one()
        assert journal.content == "daily content"
        assert journal.archived_at is not None
        assert AIAgentActivity.query.filter_by(user_id=user.id).count() == 3
        assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_weekly_rollup_uses_recent_daily_and_upserts(app, monkeypatch):
    with app.app_context():
        user = User(username="weekly_user", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.api_url = "https://api.deepseek.com/v1/chat/completions"
        setting.api_key = "sk-test"
        setting.model = "deepseek-chat"
        db.session.commit()

        sunday = _recent_sunday_at(21, 5)
        for offset in range(7):
            day = (sunday - timedelta(days=offset)).date()
            db.session.add(
                AIAgentJournal(
                    user_id=user.id,
                    period="daily",
                    start_date=day,
                    end_date=day,
                    title=f"{day.isoformat()} 日志",
                    content=f"daily {offset}",
                    archived_at=sunday,
                )
            )
        db.session.commit()

        _patch_post(monkeypatch, {"choices": [{"message": {"content": "weekly content"}}]})
        result = generate_weekly_journal_from_recent_daily(user.id, now=sunday, force=True)
        assert result["ok"] is True
        assert result["skipped"] is False

        journal = AIAgentJournal.query.filter_by(user_id=user.id, period="weekly").one()
        assert journal.content == "weekly content"


def test_prune_previous_day_happens_at_noon(app):
    with app.app_context():
        user = User(username="prune_user", is_approved=True)
        user.set_password("Password1!")
        db.session.add(user)
        db.session.commit()

        local_base = _today_at(12, 5)
        old_time = local_base - timedelta(days=1, hours=-6)
        new_time = local_base.replace(hour=9, minute=0)
        db.session.add(
            AIAgentActivity(
                user_id=user.id,
                event_type="page_view",
                label="yesterday",
                metadata_json="{}",
                created_at=old_time.astimezone(),
            )
        )
        db.session.add(
            AIAgentActivity(
                user_id=user.id,
                event_type="page_view",
                label="today",
                metadata_json="{}",
                created_at=new_time.astimezone(),
            )
        )
        db.session.commit()

        result = prune_previous_day_activities(user.id, now=local_base)
        labels = [item.label for item in AIAgentActivity.query.filter_by(user_id=user.id).all()]

        assert result["ok"] is True
        assert result["deleted"] == 1
        assert labels == ["today"]


def test_journal_page_renders_calendar(login_client, app):
    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        today = datetime.now().date()
        db.session.add(
            AIAgentJournal(
                user_id=user.id,
                period="daily",
                start_date=today,
                end_date=today,
                title=f"{today.isoformat()} journal",
                content="today journal",
            )
        )
        db.session.commit()

    resp = login_client.get("/journals/")
    assert resp.status_code == 200
    assert b"today journal" in resp.data
