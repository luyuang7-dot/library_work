from datetime import datetime, timedelta

from app.extensions import db
from app.models import AIAgentActivity, AIAgentJournal, AIAgentSetting, User
from app.security import AI_AGENT_API_KEY_PREFIX
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


def test_ai_agent_setting_and_activity_are_user_scoped(app):
    with app.app_context():
        u1 = User(username="agent_a")
        u1.set_password("pw123456")
        u2 = User(username="agent_b")
        u2.set_password("pw123456")
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


def test_ai_agent_state_update_is_user_scoped(client):
    with client.application.app_context():
        user = User(username="alpha", email="alpha@example.com", is_approved=True)
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()
    client.post("/auth/login", data={"username": "alpha", "password": "pw123456"})
    resp = client.post(
        "/ai-agent/api/state",
        json={
            "agent_name": "Alpha",
            "facing": "left",
            "position_x": 120,
            "position_y": 80,
        },
    )
    assert resp.status_code == 200
    state = resp.get_json()["state"]
    assert state["agent_name"] == "Alpha"
    assert state["daily_rollup_time"] == "23:59"
    assert "scale" not in state

    client.post("/auth/logout")
    with client.application.app_context():
        user = User(username="beta", email="beta@example.com", is_approved=True)
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()
    client.post("/auth/login", data={"username": "beta", "password": "pw123456"})
    resp = client.get("/ai-agent/api/state")
    assert resp.status_code == 200
    assert resp.get_json()["state"]["agent_name"] != "Alpha"


def test_ai_agent_state_ignores_legacy_scale_payload(login_client):
    resp = login_client.post(
        "/ai-agent/api/state",
        json={"scale": 1.35, "position_x": 120, "position_y": 80},
    )
    assert resp.status_code == 200
    state = resp.get_json()["state"]
    assert state["position_x"] == 120
    assert state["position_y"] == 80
    assert "scale" not in state


def test_settings_save_ai_agent_config_without_key_echo(login_client, app):
    resp = login_client.post(
        "/settings/",
        data={
            "agent_name": "Logger",
            "agent_enabled": "on",
            "ai_api_url": "https://ai.example.test/journal",
            "ai_api_key": "sk-secret-value",
            "user_preference": "少用可爱语气，优先总结结果。",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"sk-secret-value" not in resp.data

    with app.app_context():
        setting = AIAgentSetting.query.one()
        assert setting.agent_name == "Logger"
        assert setting.api_url == "https://ai.example.test/journal"
        assert setting.api_key == "sk-secret-value"
        assert setting.api_key_ciphertext != "sk-secret-value"
        assert setting.api_key_ciphertext.startswith(AI_AGENT_API_KEY_PREFIX)
        assert setting.user_preference == "少用可爱语气，优先总结结果。"
        assert setting.daily_rollup_minute == DEFAULT_DAILY_ROLLUP_MINUTE


def test_settings_page_renders_password_change_form(login_client):
    resp = login_client.get("/settings/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="current_password"' in body
    assert 'name="new_password"' in body
    assert 'name="confirm_password"' in body
    assert 'name="user_preference"' in body
    assert 'name="mineru_url"' in body


def test_settings_change_password_success(login_client, app):
    resp = login_client.post(
        "/settings/",
        data={
            "action": "change_password",
            "current_password": "pw123456",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        assert user is not None
        assert user.check_password("NewPass123!")
        assert not user.check_password("pw123456")


def test_settings_change_password_rejects_wrong_current_password(login_client, app):
    resp = login_client.post(
        "/settings/",
        data={
            "action": "change_password",
            "current_password": "wrong-password",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        assert user is not None
        assert user.check_password("pw123456")


def test_legacy_plaintext_ai_api_key_is_migrated_on_access(app):
    with app.app_context():
        user = User(username="legacy_agent")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        setting = AIAgentSetting(user_id=user.id, agent_name="Legacy")
        setting._api_key = "sk-legacy-plain"
        db.session.add(setting)
        db.session.commit()

        loaded = get_or_create_setting(user.id)

        assert loaded.api_key == "sk-legacy-plain"
        assert loaded.api_key_ciphertext != "sk-legacy-plain"
        assert loaded.api_key_ciphertext.startswith(AI_AGENT_API_KEY_PREFIX)


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


def _local_at(hour: int, minute: int, *, year: int = 2026, month: int = 6, day: int = 14):
    base = datetime.now().astimezone()
    return base.replace(
        year=year,
        month=month,
        day=day,
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def _today_at(hour: int, minute: int):
    base = datetime.now().astimezone()
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _recent_sunday_at(hour: int, minute: int):
    base = _today_at(hour, minute)
    delta = (base.weekday() - 6) % 7
    return base - timedelta(days=delta)


def test_daily_rollup_generation_at_2359(app, monkeypatch):
    with app.app_context():
        user = User(username="rollup_user")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.api_url = "https://api.deepseek.com/v1/chat/completions"
        setting.api_key = "sk-test"
        setting.model = "deepseek-chat"
        db.session.commit()

        rollup_time = _local_at(23, 59, year=2026, month=6, day=17)
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

        result = run_due_daily_rollups(
            user.id,
            now=rollup_time,
        )

        assert result[0]["ok"] is True
        assert result[0]["skipped"] is False
        assert result[1]["skipped"] is True
        assert result[1]["reason"] == "not_prune_time"

        journal = AIAgentJournal.query.filter_by(user_id=user.id, period="daily").one()
        assert journal.content == "daily content"
        assert journal.archived_at is not None
        assert AIAgentActivity.query.filter_by(user_id=user.id).count() == 3
        assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_daily_rollup_waits_until_2359(app, monkeypatch):
    with app.app_context():
        user = User(username="time_user")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.api_url = "https://api.deepseek.com/v1/chat/completions"
        setting.api_key = "sk-test"
        setting.model = "deepseek-chat"
        db.session.commit()

        record_activity(user.id, "page_view", "before due")
        _patch_post(monkeypatch, {"choices": [{"message": {"content": "unused"}}]})

        early = run_due_daily_rollups(
            user.id,
            now=_today_at(23, 58),
        )
        assert early[0]["skipped"] is True
        assert early[0]["reason"] == "not_due"
        assert early[1]["skipped"] is True
        assert early[1]["reason"] == "not_prune_time"


def test_weekly_rollup_uses_recent_daily_and_upserts(app, monkeypatch):
    with app.app_context():
        user = User(username="weekly_user")
        user.set_password("pw123456")
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

        again = generate_weekly_journal_from_recent_daily(
            user.id,
            now=sunday.replace(minute=10),
            force=False,
        )
        assert again["skipped"] is True
        assert again["reason"] == "already_generated"


def test_weekly_rollup_skips_without_daily_journals(app, monkeypatch):
    with app.app_context():
        user = User(username="weekly_empty")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.api_url = "https://api.deepseek.com/v1/chat/completions"
        setting.api_key = "sk-test"
        setting.model = "deepseek-chat"
        db.session.commit()

        _patch_post(monkeypatch, {"choices": [{"message": {"content": "weekly content"}}]})
        sunday = _recent_sunday_at(21, 5)
        result = generate_weekly_journal_from_recent_daily(user.id, now=sunday, force=True)
        assert result["skipped"] is True
        assert result["reason"] == "no_archived_daily_journals"


def test_rollup_time_helpers():
    assert format_daily_rollup_time(DEFAULT_DAILY_ROLLUP_MINUTE) == "23:59"
    assert format_fixed_prune_time() == "12:00"


def test_build_messages_include_agent_name_and_user_preference(app):
    with app.app_context():
        user = User(username="prompt_user")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        setting = get_or_create_setting(user.id)
        setting.agent_name = "阿卷"
        setting.user_preference = "突出重点，少写抒情句。"
        db.session.commit()

        messages = _build_messages(setting, "today", [])

        assert "阿卷" in messages[0]["content"]
        assert "突出重点，少写抒情句。" in messages[0]["content"]


def test_prune_previous_day_happens_at_noon(app):
    with app.app_context():
        user = User(username="prune_user")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.commit()

        local_base = _local_at(12, 5, year=2026, month=6, day=17)
        old_time = local_base.replace(day=16, hour=18, minute=0)
        new_time = local_base.replace(day=17, hour=9, minute=0)
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


def test_journal_page_requires_login(client):
    resp = client.get("/journals/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]
