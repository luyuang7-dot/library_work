"""Idempotent startup schema fixes for legacy databases."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

_DOC_NEW_COLUMNS = {
    "barcode": "VARCHAR(64) NULL",
    "copy_no": "VARCHAR(64) NULL",
}

_AI_AGENT_SETTING_NEW_COLUMNS = {
    "last_rollup_at": "DATETIME NULL",
    "daily_rollup_minute": "INTEGER NOT NULL DEFAULT 1439",
    "user_preference": "VARCHAR(500) NOT NULL DEFAULT ''",
}

_AI_AGENT_SETTING_DROP_COLUMNS = ("tone", "role", "personality")

_AI_AGENT_JOURNAL_NEW_COLUMNS = {
    "archived_at": "DATETIME NULL",
}

_USER_NEW_COLUMNS = {
    "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
    "can_review_registrations": "BOOLEAN NOT NULL DEFAULT 0",
    "is_approved": "BOOLEAN NOT NULL DEFAULT 1",
    "approval_status": "ENUM('pending','approved','rejected') NOT NULL DEFAULT 'approved'",
}


def ensure_user_admin_columns(session: Session) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("users")}
    for name, ddl in _USER_NEW_COLUMNS.items():
        if name in existing:
            continue
        session.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
    session.commit()

    session.execute(
        text(
            "UPDATE users "
            "SET is_admin = COALESCE(is_admin, 0), "
            "can_review_registrations = CASE "
            "WHEN COALESCE(is_admin, 0) = 1 THEN 1 "
            "ELSE COALESCE(can_review_registrations, 0) "
            "END, "
            "is_approved = COALESCE(is_approved, 1), "
            "approval_status = CASE "
            "WHEN COALESCE(is_approved, 0) = 1 THEN 'approved' "
            "WHEN approval_status IS NULL OR approval_status = '' THEN 'pending' "
            "ELSE approval_status "
            "END"
        )
    )
    session.commit()


def ensure_document_columns(session: Session) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)
    if "documents" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("documents")}
    for name, ddl in _DOC_NEW_COLUMNS.items():
        if name in existing:
            continue
        session.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {ddl}"))
    session.commit()


def ensure_ai_agent_columns(session: Session) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("ai_agent_settings")}
    for name, ddl in _AI_AGENT_SETTING_NEW_COLUMNS.items():
        if name in existing:
            continue
        session.execute(text(f"ALTER TABLE ai_agent_settings ADD COLUMN {name} {ddl}"))
    session.commit()

    inspector = inspect(bind)
    if "ai_agent_journals" not in inspector.get_table_names():
        return

    existing_journal_columns = {
        column["name"] for column in inspector.get_columns("ai_agent_journals")
    }
    for name, ddl in _AI_AGENT_JOURNAL_NEW_COLUMNS.items():
        if name in existing_journal_columns:
            continue
        session.execute(text(f"ALTER TABLE ai_agent_journals ADD COLUMN {name} {ddl}"))
    session.commit()

    inspector = inspect(bind)
    existing_setting_columns = {
        column["name"] for column in inspector.get_columns("ai_agent_settings")
    }
    for name in _AI_AGENT_SETTING_DROP_COLUMNS:
        if name not in existing_setting_columns:
            continue
        session.execute(text(f"ALTER TABLE ai_agent_settings DROP COLUMN {name}"))
    session.commit()


def ensure_ai_agent_settings_rows(session: Session) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    session.execute(
        text(
            "INSERT INTO ai_agent_settings (user_id, agent_name, enabled, facing, position_x, position_y, user_preference, daily_rollup_minute, created_at, updated_at) "
            "SELECT u.id, 'AI助手', 1, 'right', 24, 24, '', 1439, NOW(), NOW() "
            "FROM users u "
            "LEFT JOIN ai_agent_settings s ON s.user_id = u.id "
            "WHERE s.user_id IS NULL"
        )
    )
    session.commit()
