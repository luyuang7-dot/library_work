"""Course-project baseline schema without stamp/A-LSP/MARC legacy tables."""

from __future__ import annotations

from alembic import op

from app import models  # noqa: F401
from app.extensions import db

revision = "20260624_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    db.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    db.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
