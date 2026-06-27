from app.extensions import db
from app.models import Category, Document, User
from app.services.bibtex_io import import_bibtex, import_single_entry, parse_entries


def test_parse_entries_single():
    text = "@article{key1, title={Foo}, year={2020}, author={Alice}}"
    entries = parse_entries(text)
    assert len(entries) == 1
    assert entries[0]["title"].strip("{}") == "Foo"


def test_parse_entries_empty():
    assert parse_entries("") == []
    assert parse_entries("   \n  ") == []


def test_parse_entries_multi():
    text = """
    @article{a, title={A}, year={2020}}
    @inproceedings{b, title={B}, year={2021}}
    """
    entries = parse_entries(text)
    assert len(entries) == 2
    assert {e["ENTRYTYPE"] for e in entries} == {"article", "inproceedings"}


def _seed_user(app, username="u_imp"):
    with app.app_context():
        u = User(username=username, email=f"{username}@x.com")
        u.set_password("pw123456")
        db.session.add(u)
        db.session.commit()
        return u.id


def test_import_single_entry_creates_document(app):
    uid = _seed_user(app, "u_create")
    with app.app_context():
        entry = parse_entries(
            "@article{k, title={Paper One}, year={2021}, author={Alice and Bob}, "
            "journal={Nature}, doi={10.1/abc}}"
        )[0]
        result = import_single_entry(entry, uid)
        db.session.commit()
        assert result["created"] is not None
        assert result["skipped_reason"] is None
        assert result["created"].title == "Paper One"
        assert result["created"].publication_year == 2021
        assert result["created"].doi == "10.1/abc"
        assert [a.name for a in result["created"].authors] == ["Alice", "Bob"]
        assert result["created"].source.name == "Nature"


def test_import_single_entry_skips_when_no_title(app):
    uid = _seed_user(app, "u_notitle")
    with app.app_context():
        entry = {"ENTRYTYPE": "article", "ID": "k", "title": "", "year": "2021"}
        result = import_single_entry(entry, uid)
        assert result["created"] is None
        assert result["skipped_reason"] is not None
        assert "title" in result["skipped_reason"].lower() or "标题" in result["skipped_reason"]


def test_import_single_entry_skips_duplicate_by_doi(app):
    uid = _seed_user(app, "u_doi")
    with app.app_context():
        existing = Document(user_id=uid, title="Existing", doi="10.1/dup")
        db.session.add(existing)
        db.session.commit()
        entry = parse_entries(
            "@article{k, title={Different Title}, year={2021}, doi={10.1/dup}}"
        )[0]
        result = import_single_entry(entry, uid)
        assert result["created"] is None
        assert result["skipped_reason"] is not None
        assert str(existing.id) in result["skipped_reason"]


def test_import_single_entry_skips_duplicate_by_title_year(app):
    uid = _seed_user(app, "u_ty")
    with app.app_context():
        existing = Document(user_id=uid, title="Same Title", publication_year=2020)
        db.session.add(existing)
        db.session.commit()
        entry = parse_entries("@article{k, title={Same Title}, year={2020}}")[0]
        result = import_single_entry(entry, uid)
        assert result["created"] is None
        assert result["skipped_reason"] is not None


def test_import_single_entry_with_category(app):
    uid = _seed_user(app, "u_cat")
    with app.app_context():
        cat = Category(user_id=uid, name="ML")
        db.session.add(cat)
        db.session.commit()
        cat_id = cat.id
        entry = parse_entries("@article{k, title={CatPaper}, year={2022}}")[0]
        result = import_single_entry(entry, uid, category_id=cat_id)
        db.session.commit()
        assert result["created"].category_id == cat_id


def test_import_single_entry_does_not_commit(app):
    uid = _seed_user(app, "u_nocommit")
    with app.app_context():
        entry = parse_entries("@article{k, title={Trans}, year={2022}}")[0]
        result = import_single_entry(entry, uid)
        assert result["created"] is not None
        db.session.rollback()
        assert Document.query.filter_by(user_id=uid, title="Trans").count() == 0


def test_import_bibtex_backward_compatible(app):
    uid = _seed_user(app, "u_compat")
    with app.app_context():
        text = (
            "@article{a, title={A1}, year={2020}}\n"
            "@article{b, title={}, year={2021}}\n"
            "@article{c, title={A1}, year={2020}}"
        )
        created, skipped = import_bibtex(text, uid)
        assert created == 1
        assert skipped == 2
