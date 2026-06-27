import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Document, User


def _make_user(username="u1"):
    user = User(username=username, email=f"{username}@e.com")
    user.set_password("pw123456")
    db.session.add(user)
    db.session.commit()
    return user


def _make_doc(user_id, title="t", barcode=None, copy_no=None):
    document = Document(
        user_id=user_id,
        title=title,
        document_type="book",
        barcode=barcode,
        copy_no=copy_no,
    )
    db.session.add(document)
    return document


def test_document_has_barcode_and_copy_no_columns(app):
    with app.app_context():
        user = _make_user()
        _make_doc(user.id, title="t1", barcode="B001", copy_no="C001")
        db.session.commit()

        document = Document.query.filter_by(title="t1").first()
        assert document.barcode == "B001"
        assert document.copy_no == "C001"


def test_barcode_unique_per_user(app):
    with app.app_context():
        user = _make_user()
        _make_doc(user.id, title="a", barcode="DUP")
        db.session.commit()

        _make_doc(user.id, title="b", barcode="DUP")
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_copy_no_unique_per_user(app):
    with app.app_context():
        user = _make_user()
        _make_doc(user.id, title="a", copy_no="CN01")
        db.session.commit()

        _make_doc(user.id, title="b", copy_no="CN01")
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_barcode_can_be_null_multiple_times(app):
    with app.app_context():
        user = _make_user()
        _make_doc(user.id, title="a")
        _make_doc(user.id, title="b")
        db.session.commit()
        assert Document.query.filter_by(barcode=None).count() == 2


def test_same_barcode_allowed_across_users(app):
    with app.app_context():
        user1 = _make_user("u1")
        user2 = _make_user("u2")
        _make_doc(user1.id, title="a", barcode="SHARED")
        _make_doc(user2.id, title="b", barcode="SHARED")
        db.session.commit()
        assert Document.query.filter_by(barcode="SHARED").count() == 2


def test_documents_new_form_accepts_barcode_and_copy_no(login_client, app):
    response = login_client.post(
        "/documents/new",
        data={
            "title": "Sample",
            "document_type": "book",
            "barcode": "  B001  ",
            "copy_no": "C001",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        doc = Document.query.filter_by(title="Sample").first()
        assert doc.barcode == "B001"
        assert doc.copy_no == "C001"


def test_documents_edit_form_updates_barcode_and_copy_no(login_client, app):
    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        doc = Document(user_id=user.id, title="X", document_type="book")
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

    login_client.post(
        f"/documents/{doc_id}/edit",
        data={"title": "X", "barcode": "B009", "copy_no": "C009"},
        follow_redirects=True,
    )
    with app.app_context():
        doc = db.session.get(Document, doc_id)
        assert doc.barcode == "B009"
        assert doc.copy_no == "C009"


def test_documents_form_empty_barcode_means_null(login_client, app):
    login_client.post(
        "/documents/new",
        data={"title": "Y", "document_type": "book", "barcode": "   ", "copy_no": ""},
        follow_redirects=True,
    )
    with app.app_context():
        doc = Document.query.filter_by(title="Y").first()
        assert doc.barcode is None
        assert doc.copy_no is None


def test_documents_form_rejects_duplicate_barcode(login_client, app):
    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        db.session.add(
            Document(user_id=user.id, title="A", document_type="book", barcode="DUP")
        )
        db.session.commit()

    response = login_client.post(
        "/documents/new",
        data={"title": "B", "document_type": "book", "barcode": "DUP"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "DUP" in body or "已被" in body or "条码" in body
    with app.app_context():
        assert Document.query.filter_by(title="B").count() == 0


def test_edit_template_renders_barcode_inputs(login_client, app):
    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        doc = Document(
            user_id=user.id,
            title="T",
            document_type="book",
            barcode="BX",
            copy_no="CX",
        )
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

    response = login_client.get(f"/documents/{doc_id}/edit")
    body = response.get_data(as_text=True)
    assert 'name="barcode"' in body
    assert 'name="copy_no"' in body
    assert 'value="BX"' in body
    assert 'value="CX"' in body


def test_new_template_renders_empty_barcode_inputs(login_client):
    response = login_client.get("/documents/new")
    body = response.get_data(as_text=True)
    assert 'name="barcode"' in body
    assert 'name="copy_no"' in body
