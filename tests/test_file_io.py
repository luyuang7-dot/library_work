import io

from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Document, File, User
from app.services.file_io import save_uploaded_files


def _make_filestorage(name="sample.pdf", content=b"%PDF-1.1\n%dummy\n"):
    return FileStorage(
        stream=io.BytesIO(content),
        filename=name,
        content_type="application/pdf",
    )


def test_save_uploaded_files_creates_file_record_and_writes_disk(app):
    with app.app_context():
        user = User(username="u1", email="u1@x.com")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.flush()
        doc = Document(user_id=user.id, title="T")
        db.session.add(doc)
        db.session.flush()

        uploaded = _make_filestorage("a.pdf", b"%PDF-1.1\nhello\n")
        saved, skipped = save_uploaded_files(doc, [uploaded], user.id)
        db.session.commit()

        assert len(saved) == 1
        assert saved[0].exists()
        assert skipped == []
        records = File.query.filter_by(document_id=doc.id).all()
        assert len(records) == 1
        assert records[0].original_name == "a.pdf"
        assert records[0].mime_type == "application/pdf"


def test_save_uploaded_files_skips_disallowed_extension(app):
    with app.app_context():
        user = User(username="u2", email="u2@x.com")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.flush()
        doc = Document(user_id=user.id, title="T")
        db.session.add(doc)
        db.session.flush()

        uploaded = _make_filestorage("notes.exe", b"MZ\x90\x00")
        saved, skipped = save_uploaded_files(doc, [uploaded], user.id)

        assert saved == []
        assert skipped == ["notes.exe"]
        assert File.query.count() == 0


def test_save_uploaded_files_skips_empty_filename(app):
    with app.app_context():
        user = User(username="u3", email="u3@x.com")
        user.set_password("pw123456")
        db.session.add(user)
        db.session.flush()
        doc = Document(user_id=user.id, title="T")
        db.session.add(doc)
        db.session.flush()

        uploaded = _make_filestorage("", b"")
        saved, skipped = save_uploaded_files(doc, [uploaded], user.id)

        assert saved == []
        assert skipped == []
