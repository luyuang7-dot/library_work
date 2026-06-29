"""Remove floating AI agent UI columns and normalize companion name."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260629_0003"
down_revision = "20260628_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("ai_agent_settings")}
    for column_name in ("facing", "position_x", "position_y"):
        if column_name in existing:
            op.drop_column("ai_agent_settings", column_name)

    op.execute(
        "UPDATE ai_agent_settings "
        "SET agent_name = 'Eyjafjalla' "
        "WHERE agent_name IN ('AI??', 'AI鍔╂墜', 'AI閸斺晜澧?', '艾雅法拉') "
        "OR agent_name IS NULL OR agent_name = ''"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_agent_settings" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("ai_agent_settings")}
    if "facing" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("facing", sa.String(length=8), nullable=False, server_default="right"),
        )
    if "position_x" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("position_x", sa.Integer(), nullable=False, server_default="24"),
        )
    if "position_y" not in existing:
        op.add_column(
            "ai_agent_settings",
            sa.Column("position_y", sa.Integer(), nullable=False, server_default="24"),
        )

    op.execute(
        "UPDATE ai_agent_settings "
        "SET agent_name = '艾雅法拉' "
        "WHERE agent_name = 'Eyjafjalla' OR agent_name IS NULL OR agent_name = ''"
    )

