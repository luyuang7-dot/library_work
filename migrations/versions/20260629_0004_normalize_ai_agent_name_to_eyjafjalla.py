"""Normalize AI assistant name to Eyjafjalla.

Revision ID: 20260629_0004
Revises: 20260629_0003
Create Date: 2026-06-29 17:20:00
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260629_0004"
down_revision = "20260629_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            "UPDATE ai_agent_settings "
            "SET agent_name = 'Eyjafjalla'"
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE ai_agent_settings "
            "SET agent_name = '艾雅法拉' "
            "WHERE agent_name = 'Eyjafjalla'"
        )
    )
