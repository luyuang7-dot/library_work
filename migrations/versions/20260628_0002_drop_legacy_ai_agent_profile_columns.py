"""Drop legacy AI agent profile columns removed from the course project."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260628_0002"
down_revision = "20260624_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("ai_agent_settings")}
    for column_name in ("tone", "role", "personality"):
        if column_name in existing:
            op.drop_column("ai_agent_settings", column_name)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("ai_agent_settings")}
    if "tone" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("tone", sa.String(length=32), nullable=False, server_default="gentle"),
        )
    if "role" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("role", sa.String(length=32), nullable=False, server_default="companion"),
        )
    if "personality" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("personality", sa.String(length=32), nullable=False, server_default="thoughtful"),
        )
