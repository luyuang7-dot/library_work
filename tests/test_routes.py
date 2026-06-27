from app.extensions import db
from app.models import Category, Document, Tag, User


def test_index_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_register_login_flow(client, app):
    resp = client.post(
        "/auth/register",
        data={
            "username": "alice",
            "password": "pwd12345",
            "password2": "pwd12345",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username="alice").first()
        assert user is not None
        assert user.is_approved is False
        user.is_approved = True
        db.session.commit()

    resp = client.post(
        "/auth/login",
        data={
            "username": "alice",
            "password": "pwd12345",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    logout_resp = client.post("/auth/logout", follow_redirects=False)
    assert logout_resp.status_code == 302


def test_document_crud(client, approved_user_factory, login_as):
    approved_user_factory("bob")
    login_as("bob")

    resp = client.post(
        "/documents/new",
        data={
            "title": "Test Paper",
            "document_type": "journal_article",
            "publication_year": "2024",
            "source_name": "Nature",
            "source_type": "journal",
            "publisher_name": "Springer",
            "authors_raw": "Alice | MIT | a@x.com\nBob | Stanford",
            "keywords_raw": "ml, graph",
            "abstract": "abc",
            "reading_status": "unread",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Test Paper" in resp.data

    resp = client.get("/documents/search?q=Alice")
    assert b"Test Paper" in resp.data

    resp = client.get("/documents/1")
    assert resp.status_code == 200
    assert b"Springer" in resp.data
    assert b"graph" in resp.data

    resp = client.post("/documents/1/delete", follow_redirects=True)
    assert resp.status_code == 200


def test_tags_and_advanced_search(client, app, approved_user_factory, login_as):
    approved_user_factory("tagger")
    login_as("tagger")

    resp = client.post(
        "/documents/new",
        data={
            "title": "Polymer Chemistry",
            "document_type": "journal_article",
            "publication_year": "2024",
            "source_name": "Journal of Chemistry",
            "source_type": "journal",
            "authors_raw": "Alice",
            "keywords_raw": "catalyst",
            "tags_raw": "tag-polymer, tag-materials",
            "abstract": "polymer membrane study",
            "reading_status": "unread",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"tag-polymer" in resp.data
    assert b"tag-materials" in resp.data

    client.post(
        "/documents/new",
        data={
            "title": "Database Systems",
            "document_type": "conference_paper",
            "publication_year": "2019",
            "source_name": "VLDB",
            "source_type": "conference",
            "authors_raw": "Bob",
            "keywords_raw": "database",
            "tags_raw": "tag-database",
            "abstract": "relational query processing",
            "reading_status": "unread",
        },
        follow_redirects=True,
    )

    for query in [
        "q=Polymer",
        "q=membrane",
        "author=Alice",
        "source=Chemistry",
        "q=catalyst",
        "q=tag-materials",
        "year_from=2020&year_to=2025",
    ]:
        resp = client.get(f"/documents/search?{query}")
        assert b"Polymer Chemistry" in resp.data
        assert b"Database Systems" not in resp.data

    with app.app_context():
        polymer_tag = Tag.query.filter_by(name="tag-polymer").first()
        assert polymer_tag is not None

    resp = client.get(f"/documents/search?tags={polymer_tag.id}&year_to=2020")
    assert b"Polymer Chemistry" not in resp.data

    resp = client.post(
        "/documents/1/edit",
        data={
            "title": "Polymer Chemistry",
            "document_type": "journal_article",
            "publication_year": "2024",
            "source_name": "Journal of Chemistry",
            "source_type": "journal",
            "authors_raw": "Alice#1",
            "keywords_raw": "catalyst",
            "tags_raw": "tag-updated",
            "abstract": "polymer membrane study",
            "reading_status": "unread",
        },
        follow_redirects=True,
    )
    assert b"tag-updated" in resp.data
    assert b"tag-materials" not in resp.data

    resp = client.get("/library/")
    assert b"tag-updated" in resp.data

    resp = client.get("/library/cleanup_scan")
    payload = resp.get_json()
    assert "tag-materials" in payload["orphans"]["tags"]


def test_bulk_category_updates_selected_documents(
    client, app, approved_user_factory, login_as
):
    user_id = approved_user_factory("batcher")
    login_as("batcher")

    with app.app_context():
        category = Category(user_id=user_id, name="Machine Learning")
        db.session.add(category)
        db.session.flush()
        db.session.add_all(
            [
                Document(user_id=user_id, title="Doc A"),
                Document(user_id=user_id, title="Doc B"),
                Document(user_id=user_id, title="Doc C"),
            ]
        )
        db.session.commit()
        category_id = category.id

    resp = client.post(
        "/documents/bulk-category",
        data={
            "doc_ids": ["1", "3"],
            "category_id": str(category_id),
            "return_page": "1",
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Document, 1).category_id == category_id
        assert db.session.get(Document, 2).category_id is None
        assert db.session.get(Document, 3).category_id == category_id


def test_bulk_category_can_clear_category(client, app, approved_user_factory, login_as):
    user_id = approved_user_factory("clearcat")
    login_as("clearcat")

    with app.app_context():
        category = Category(user_id=user_id, name="To Clear")
        db.session.add(category)
        db.session.flush()
        document = Document(user_id=user_id, title="Doc A", category_id=category.id)
        db.session.add(document)
        db.session.commit()

    resp = client.post(
        "/documents/bulk-category",
        data={
            "doc_ids": ["1"],
            "category_id": "__none__",
            "return_page": "1",
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200

    with app.app_context():
        assert db.session.get(Document, 1).category_id is None
