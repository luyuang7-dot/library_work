"""Tags must travel through merge_preview/apply/rollback like the other dictionaries."""

from app.extensions import db
from app.models import Document, DocumentTag, Tag, User
from app.services import dict_cleanup


def _seed_user_with_duplicate_tags(name_a: str = "Chemistry", name_b: str = "chemistry"):
    """Create one user, two tags whose normalized names collide, plus a doc
    linked to the alias (lower-id tag is canonical)."""
    user = User(username="dupper", email="d@x.com")
    user.set_password("pw123456")
    db.session.add(user)
    db.session.flush()

    canonical_tag = Tag(user_id=user.id, name=name_a)
    alias_tag = Tag(user_id=user.id, name=name_b)
    db.session.add_all([canonical_tag, alias_tag])
    db.session.flush()

    doc = Document(user_id=user.id, title="A polymer paper")
    db.session.add(doc)
    db.session.flush()

    db.session.add(DocumentTag(document_id=doc.id, tag_id=alias_tag.id))
    db.session.commit()

    return user.id, canonical_tag.id, alias_tag.id, doc.id


def test_merge_preview_surfaces_duplicate_tags(app):
    with app.app_context():
        uid, canonical_id, alias_id, _ = _seed_user_with_duplicate_tags()

        preview = dict_cleanup.merge_preview(uid)
        plan = preview["plan"]

        assert "tags" in plan, "tag duplicates must show up in the merge plan"
        assert len(plan["tags"]) == 1
        entry = plan["tags"][0]
        assert entry["canonical_id"] == canonical_id
        assert entry["alias_ids"] == [alias_id]
        assert entry["impacted_docs"] == 1


def test_merge_apply_merges_duplicate_tags(app):
    with app.app_context():
        uid, canonical_id, alias_id, doc_id = _seed_user_with_duplicate_tags()

        result = dict_cleanup.merge_apply(uid)
        assert result["ok"] is True
        assert result["aliases_merged"] >= 1

        assert db.session.get(Tag, alias_id) is None, "alias tag should be deleted"
        assert db.session.get(Tag, canonical_id) is not None

        links = DocumentTag.query.filter_by(document_id=doc_id).all()
        assert len(links) == 1
        assert links[0].tag_id == canonical_id


def test_merge_rollback_restores_tag_link(app):
    with app.app_context():
        uid, canonical_id, alias_id, doc_id = _seed_user_with_duplicate_tags()

        dict_cleanup.merge_apply(uid)
        rollback = dict_cleanup.merge_rollback_last(uid)
        assert rollback["ok"] is True

        assert db.session.get(Tag, alias_id) is not None, "rolled-back tag should be back"
        links = DocumentTag.query.filter_by(document_id=doc_id).all()
        assert len(links) == 1
        assert links[0].tag_id == alias_id, "document should re-link to original alias tag"
