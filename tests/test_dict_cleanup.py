from __future__ import annotations

from app.extensions import db
from app.models import Document, DocumentAuthor, DocumentTag, Tag, User
from app.services import dict_cleanup, upsert


def _seed_user_with_duplicate_tags():
    user = User(username="dupper", email="d@x.com", is_approved=True)
    user.set_password("Password1!")
    db.session.add(user)
    db.session.flush()

    canonical_tag = Tag(user_id=user.id, name="Chemistry")
    alias_tag = Tag(user_id=user.id, name="chemistry")
    db.session.add_all([canonical_tag, alias_tag])
    db.session.flush()

    doc = Document(
        user_id=user.id,
        title="A polymer paper",
        document_type="journal_article",
        reading_status="unread",
    )
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

        assert "tags" in plan
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

        assert db.session.get(Tag, alias_id) is None
        assert db.session.get(Tag, canonical_id) is not None

        links = DocumentTag.query.filter_by(document_id=doc_id).all()
        assert len(links) == 1
        assert links[0].tag_id == canonical_id


def test_merge_rollback_restores_tag_link(app):
    with app.app_context():
        uid, _canonical_id, alias_id, doc_id = _seed_user_with_duplicate_tags()

        dict_cleanup.merge_apply(uid)
        rollback = dict_cleanup.merge_rollback_last(uid)
        assert rollback["ok"] is True

        assert db.session.get(Tag, alias_id) is not None
        links = DocumentTag.query.filter_by(document_id=doc_id).all()
        assert len(links) == 1
        assert links[0].tag_id == alias_id


def test_cleanup_scan_and_apply_remove_orphans(app, approved_user_factory):
    uid = approved_user_factory("cleanup-user")
    with app.app_context():
        upsert.get_or_create_tag("孤立标签", uid)
        upsert.get_or_create_keyword("孤立关键词", uid)
        upsert.get_or_create_author("孤立作者", uid)

        scan = dict_cleanup.scan_orphans(uid)
        assert "孤立标签" in [item.name for item in scan["tags"]]

        result = dict_cleanup.delete_all_orphans(uid)
        assert result["tags"] == 1
        assert result["keywords"] == 1
        assert result["authors"] == 1


def test_prune_orphans_after_document_delete(app, approved_user_factory):
    uid = approved_user_factory("prune-user")
    with app.app_context():
        author = upsert.get_or_create_author("作者甲", uid)
        keyword = upsert.get_or_create_keyword("关键词甲", uid)
        tag = upsert.get_or_create_tag("标签甲", uid)
        source = upsert.get_or_create_source("测试期刊", uid, "journal", "测试出版社")
        doc = Document(
            user_id=uid,
            title="待清理文献",
            source=source,
            document_type="journal_article",
            reading_status="unread",
        )
        db.session.add(doc)
        db.session.flush()
        db.session.add(DocumentAuthor(document_id=doc.id, author_id=author.id, author_order=1))
        doc.keywords.append(keyword)
        doc.tags.append(tag)
        db.session.commit()

        db.session.delete(doc)
        db.session.flush()
        summary = dict_cleanup.prune_orphans_around_document([author], [keyword], [tag], source)
        db.session.commit()

        assert summary["authors"] == 1
        assert summary["keywords"] == 1
        assert summary["tags"] == 1
        assert summary["sources"] == 1
