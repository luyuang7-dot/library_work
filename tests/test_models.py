import pytest

from app.extensions import db
from app.models import (
    Category,
    Document,
    DocumentAuthor,
    Tag,
    User,
)
from app.services import upsert
from app.services.bibtex_io import export_bibtex, import_bibtex


def test_create_document_with_relationships(app, user):
    with app.app_context():
        owner = db.session.get(User, user)
        uid = owner.id
        cat = Category(user_id=uid, name="ML")
        db.session.add(cat)
        db.session.flush()
        source = upsert.get_or_create_source("Nature", uid, "journal", "Springer Nature")
        a1 = upsert.get_or_create_author("Alice", uid)
        a2 = upsert.get_or_create_author("Bob", uid)
        aff = upsert.get_or_create_affiliation("MIT", uid)
        a1.affiliations.append(aff)
        kw = upsert.get_or_create_keyword("graph", uid)
        doc = Document(
            user_id=uid,
            title="A paper",
            abstract="x",
            source=source,
            category=cat,
            publication_year=2024,
            doi="10.1/abc",
        )
        db.session.add(doc)
        db.session.flush()
        db.session.add_all(
            [
                DocumentAuthor(document_id=doc.id, author_id=a1.id, author_order=1),
                DocumentAuthor(document_id=doc.id, author_id=a2.id, author_order=2),
            ]
        )
        doc.keywords.append(kw)
        db.session.commit()

        fresh = db.session.get(Document, doc.id)
        assert fresh.title == "A paper"
        assert [author.name for author in fresh.authors] == ["Alice", "Bob"]
        assert fresh.keywords[0].name == "graph"
        assert fresh.source.publisher.name == "Springer Nature"
        assert fresh.category.name == "ML"


def test_upsert_strict_author_rejects_duplicate(app, user):
    with app.app_context():
        author = upsert.get_or_create_author("Carol", user)
        assert author.code == 1
        with pytest.raises(ValueError):
            upsert.get_or_create_author("Carol", user)


def test_allocate_new_author_assigns_increasing_codes(app, user):
    with app.app_context():
        first = upsert.allocate_new_author("Dan", user)
        second = upsert.allocate_new_author("Dan", user)
        assert first.code == 1 and second.code == 2
        assert first.id != second.id


def test_upsert_lenient_author_reuses(app, user):
    with app.app_context():
        first = upsert.get_or_create_author_lenient("Eve", user)
        second = upsert.get_or_create_author_lenient("Eve", user)
        assert first.id == second.id


def test_upsert_source_reuses_existing(app, user):
    with app.app_context():
        s1 = upsert.get_or_create_source("ICML", user, "conference")
        s2 = upsert.get_or_create_source("ICML", user, "conference")
        assert s1.id == s2.id


def test_upsert_tag_scoped_by_user(app):
    with app.app_context():
        u1 = User(username="tag_u1")
        u1.set_password("pw123456")
        u2 = User(username="tag_u2")
        u2.set_password("pw123456")
        db.session.add_all([u1, u2])
        db.session.flush()

        t1 = upsert.get_or_create_tag("chemistry", u1.id)
        t2 = upsert.get_or_create_tag("chemistry", u1.id)
        t3 = upsert.get_or_create_tag("chemistry", u2.id)

        doc = Document(user_id=u1.id, title="Tagged Paper")
        db.session.add(doc)
        db.session.flush()
        doc.tags.append(t1)
        db.session.commit()

        assert t1.id == t2.id
        assert t1.id != t3.id
        assert Tag.query.filter_by(name="chemistry").count() == 2
        assert [tag.name for tag in db.session.get(Document, doc.id).tags] == ["chemistry"]


def test_bibtex_roundtrip(app, user):
    bib = """@article{x1, title={Hello}, author={Smith, John and Doe, Jane},
              journal={Nature}, year={2020}, doi={10.1/h}}"""
    with app.app_context():
        created, skipped = import_bibtex(bib, user)
        assert created == 1 and skipped == 0
        created2, skipped2 = import_bibtex(bib, user)
        assert created2 == 0 and skipped2 == 1
        docs = Document.query.filter_by(user_id=user).all()
        out = export_bibtex(docs)
        assert "Hello" in out
        assert "Smith, John and Doe, Jane" in out
