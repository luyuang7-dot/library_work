from __future__ import annotations

import io
from unittest.mock import patch

from app.extensions import db
from app.models import Category, Document


def _pdf_bytes(name: str = "sample.pdf", content: bytes = b"%PDF-1.4 sample"):
    return io.BytesIO(content), name


def test_batch_page_requires_login(client):
    resp = client.get("/bibtex/batch", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_batch_page_renders(login_client):
    resp = login_client.get("/bibtex/batch")
    assert resp.status_code == 200


@patch("app.blueprints.batch_bibtex.mineru_client.parse_pdf")
def test_batch_recognize_returns_suggested_fields(mock_parse_pdf, login_client):
    mock_parse_pdf.return_value = {
        "md": "# 批量测试论文\n\n王五\n\nAbstract\n批量摘要",
        "content_list": [
            {"text": "批量测试论文", "text_level": 1},
            {"text": "王五", "text_level": 0},
            {"text": "Abstract", "text_level": 2},
            {"text": "批量摘要", "text_level": 0},
        ],
    }

    stream, filename = _pdf_bytes()
    resp = login_client.post(
        "/bibtex/batch/recognize",
        data={"pdf": (stream, filename)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["suggested_fields"]["title"] == "批量测试论文"


@patch("app.blueprints.batch_bibtex.mineru_client.parse_pdf")
def test_batch_import_creates_document_from_pdf(mock_parse_pdf, login_client, app):
    mock_parse_pdf.return_value = {"md": "", "content_list": []}

    with app.app_context():
        from app.models import User

        current_user = User.query.filter_by(username="tester").first()
        category = Category(user_id=current_user.id, name="批量分类")
        db.session.add(category)
        db.session.commit()
        category_id = category.id

    stream, filename = _pdf_bytes("import.pdf", b"%PDF-1.4 import")
    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": (stream, filename),
            "title": "批量导入文献",
            "document_type": "journal_article",
            "source_type": "journal",
            "publication_year": "2024",
            "source_name": "软件工程",
            "publisher_name": "高教社",
            "authors_raw": "王五",
            "keywords_raw": "测试, 批量",
            "reading_status": "unread",
            "default_category_id": str(category_id),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True

    with app.app_context():
        doc = Document.query.filter_by(title="批量导入文献").first()
        assert doc is not None
        assert doc.category_id == category_id


def test_batch_import_rejects_duplicate_document(login_client, app):
    with app.app_context():
        from app.models import User

        user = User.query.filter_by(username="tester").first()
        db.session.add(
            Document(
                user_id=user.id,
                title="重复文献",
                publication_year=2024,
                document_type="journal_article",
                reading_status="unread",
            )
        )
        db.session.commit()

    stream, filename = _pdf_bytes("duplicate.pdf", b"%PDF-1.4 dup")
    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": (stream, filename),
            "title": "重复文献",
            "publication_year": "2024",
            "document_type": "journal_article",
            "source_type": "journal",
            "authors_raw": "",
            "keywords_raw": "",
            "reading_status": "unread",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "duplicate"


@patch("app.blueprints.batch_bibtex.mineru_client.health_check")
def test_batch_health_proxy(mock_health_check, login_client):
    mock_health_check.return_value = {"status": "ok", "version": "3.2.0"}
    resp = login_client.get("/bibtex/batch/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
