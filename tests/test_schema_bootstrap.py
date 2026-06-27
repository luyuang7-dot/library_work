import pytest
from sqlalchemy import text

from app.extensions import db
from app.services.schema_bootstrap import ensure_document_columns


def test_ensure_document_columns_idempotent(app):
    with app.app_context():
        ensure_document_columns(db.session)
        ensure_document_columns(db.session)


def test_ensure_document_columns_adds_missing_columns(app):
    with app.app_context():
        bind = db.session.get_bind()
        if bind.dialect.name != "sqlite":
            pytest.skip("SQLite-only verification")

        db.session.execute(text("DROP TABLE IF EXISTS documents"))
        db.session.execute(
            text(
                "CREATE TABLE documents ("
                "id INTEGER PRIMARY KEY, "
                "user_id INTEGER, "
                "title TEXT"
                ")"
            )
        )
        db.session.commit()

        ensure_document_columns(db.session)

        columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(documents)")).fetchall()
        }
        assert "barcode" in columns
        assert "copy_no" in columns
