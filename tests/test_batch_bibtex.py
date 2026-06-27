import io
import time
from pathlib import Path

from sqlalchemy.exc import OperationalError


def test_batch_page_requires_login(client):
    resp = client.get("/bibtex/batch", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_batch_page_renders(login_client):
    resp = login_client.get("/bibtex/batch")
    assert resp.status_code == 200
    assert b"Batch PDF Recognition and Import" in resp.data


def test_batch_recognize_rejects_missing_pdf(login_client):
    resp = login_client.post("/bibtex/batch/recognize", data={})
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False


def test_batch_recognize_rejects_non_pdf(login_client):
    resp = login_client.post(
        "/bibtex/batch/recognize",
        data={"pdf": (io.BytesIO(b"not pdf"), "evil.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_batch_recognize_rejects_empty_pdf(login_client):
    resp = login_client.post(
        "/bibtex/batch/recognize",
        data={"pdf": (io.BytesIO(b""), "blank.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_batch_recognize_success(login_client, upload_pdf, mock_mineru):
    resp = login_client.post(
        "/bibtex/batch/recognize",
        data={"pdf": upload_pdf("paper.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["filename"] == "paper.pdf"
    assert "Fake markdown body." in payload["markdown"]
    assert "suggested_fields" in payload
    assert len(mock_mineru) == 1


def test_batch_recognize_mineru_error_returns_502(login_client, upload_pdf, monkeypatch):
    from app.services import mineru_client

    def boom(*args, **kwargs):
        raise mineru_client.MineruError("MinerU unavailable")

    monkeypatch.setattr(mineru_client, "parse_pdf", boom)
    resp = login_client.post(
        "/bibtex/batch/recognize",
        data={"pdf": upload_pdf("p.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 502
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "MinerU" in payload["error"]


def test_batch_import_creates_document_with_attachment(login_client, upload_pdf, seeded_user_id):
    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": upload_pdf("batched.pdf"),
            "title": "Batched Paper",
            "publication_year": "2023",
            "authors_raw": "Alice",
            "doi": "10.7/x",
            "document_type": "journal_article",
            "source_type": "journal",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["title"] == "Batched Paper"

    from app.models import Document

    doc = Document.query.filter_by(user_id=seeded_user_id, title="Batched Paper").first()
    assert doc is not None
    assert doc.publication_year == 2023
    assert len(doc.files) == 1
    assert doc.files[0].original_name == "batched.pdf"


def test_batch_import_missing_title(login_client, upload_pdf):
    resp = login_client.post(
        "/bibtex/batch/import",
        data={"pdf": upload_pdf(), "title": ""},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "missing_title"


def test_batch_import_duplicate_by_title_and_year(login_client, upload_pdf, seeded_user_id, app):
    from app.extensions import db
    from app.models import Document

    with app.app_context():
        existing = Document(user_id=seeded_user_id, title="A", publication_year=2020)
        db.session.add(existing)
        db.session.commit()

    resp = login_client.post(
        "/bibtex/batch/import",
        data={"pdf": upload_pdf(), "title": "A", "publication_year": "2020"},
        content_type="multipart/form-data",
    )
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "duplicate"


def test_batch_import_duplicate_by_doi(login_client, upload_pdf, seeded_user_id, app):
    from app.extensions import db
    from app.models import Document, File

    with app.app_context():
        existing = Document(user_id=seeded_user_id, title="Old", doi="10.99/dup")
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": upload_pdf("dup.pdf"),
            "title": "Different",
            "publication_year": "2023",
            "doi": "10.99/dup",
        },
        content_type="multipart/form-data",
    )
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "duplicate"
    assert str(existing_id) in payload["error_detail"]

    with app.app_context():
        assert File.query.filter_by(document_id=existing_id).count() == 0


def test_batch_import_rejects_non_pdf_attachment(login_client):
    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": (io.BytesIO(b"oops"), "evil.exe"),
            "title": "T",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_batch_import_with_category_id(login_client, upload_pdf, seeded_user_id, app):
    from app.extensions import db
    from app.models import Category, Document

    with app.app_context():
        category = Category(user_id=seeded_user_id, name="ML-batch")
        db.session.add(category)
        db.session.commit()
        cat_id = category.id

    resp = login_client.post(
        "/bibtex/batch/import",
        data={
            "pdf": upload_pdf("cb.pdf"),
            "title": "CatBatch",
            "publication_year": "2024",
            "category_id": str(cat_id),
        },
        content_type="multipart/form-data",
    )
    payload = resp.get_json()
    assert payload["ok"] is True

    with app.app_context():
        doc = Document.query.filter_by(user_id=seeded_user_id, title="CatBatch").first()
        assert doc.category_id == cat_id


def test_batch_import_rollback_cleans_orphan_attachment(
    login_client, upload_pdf, app, monkeypatch, seeded_user_id
):
    from app.extensions import db
    from app.models import Document
    from flask import current_app

    with app.app_context():
        upload_root = Path(current_app.config["UPLOAD_FOLDER"])
        user_dir = upload_root / str(seeded_user_id)
        before = set(p.name for p in user_dir.iterdir()) if user_dir.exists() else set()

    def fake_commit():
        raise OperationalError("", {}, Exception("disk full simulation"))

    monkeypatch.setattr(db.session, "commit", fake_commit)

    resp = login_client.post(
        "/bibtex/batch/import",
        data={"pdf": upload_pdf("doomed.pdf"), "title": "Doomed", "publication_year": "2024"},
        content_type="multipart/form-data",
    )
    payload = resp.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "save_failed"

    with app.app_context():
        assert Document.query.filter_by(title="Doomed").count() == 0
        upload_root = Path(current_app.config["UPLOAD_FOLDER"])
        user_dir = upload_root / str(seeded_user_id)
        if user_dir.exists():
            after = set(p.name for p in user_dir.iterdir())
            extras = after - before
            for name in extras:
                path = user_dir / name
                for _ in range(20):
                    try:
                        path.unlink(missing_ok=True)
                        break
                    except PermissionError:
                        time.sleep(0.05)


def test_batch_health_passes(login_client, monkeypatch):
    from app.services import mineru_client

    monkeypatch.setattr(
        mineru_client, "health_check", lambda url, timeout=3.0: {"status": "ok"}
    )
    resp = login_client.get("/bibtex/batch/health")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_batch_health_fails_gracefully(login_client, monkeypatch):
    from app.services import mineru_client

    def boom(url, timeout=3.0):
        raise mineru_client.MineruError("service unreachable")

    monkeypatch.setattr(mineru_client, "health_check", boom)
    resp = login_client.get("/bibtex/batch/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "service unreachable" in payload["error"]
