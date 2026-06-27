"""Detect and remove unused dictionary entries.

Dictionary tables (authors / affiliations / publishers / sources / keywords / tags)
are shared globally across users. Records not referenced by any document or
author are dead weight and can be safely removed.

Duplicates (case-insensitive name collisions) are also surfaced for review;
the merge workflow keeps an audit trail so users can roll changes back.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from ..extensions import db
from ..models import (
    Affiliation,
    Author,
    AuthorAffiliation,
    AuthorCode,
    Document,
    DocumentAuthor,
    DocumentKeyword,
    DocumentTag,
    Keyword,
    MergeAudit,
    Publisher,
    Source,
    Tag,
)

_WS = re.compile(r"\s+")
PLAN_KEYS = ("authors", "affiliations", "publishers", "sources", "keywords", "tags")


# ---- Orphan detection ----------------------------------------------------

def find_orphan_authors(user_id: int) -> list[Author]:
    return Author.query.filter_by(user_id=user_id).filter(~Author.document_links.any()).all()


def find_orphan_affiliations(user_id: int) -> list[Affiliation]:
    return Affiliation.query.filter_by(user_id=user_id).filter(~Affiliation.authors.any()).all()


def find_orphan_publishers(user_id: int) -> list[Publisher]:
    return Publisher.query.filter_by(user_id=user_id).filter(~Publisher.sources.any()).all()


def find_orphan_sources(user_id: int) -> list[Source]:
    return Source.query.filter_by(user_id=user_id).filter(~Source.documents.any()).all()


def find_orphan_keywords(user_id: int) -> list[Keyword]:
    return Keyword.query.filter_by(user_id=user_id).filter(~Keyword.documents.any()).all()


def find_orphan_tags(user_id: int) -> list[Tag]:
    return (
        Tag.query.filter_by(user_id=user_id)
        .filter(~Tag.documents.any()).all()
    )


def scan_orphans(user_id: int) -> dict[str, list]:
    return {
        "authors": find_orphan_authors(user_id),
        "affiliations": find_orphan_affiliations(user_id),
        "publishers": find_orphan_publishers(user_id),
        "sources": find_orphan_sources(user_id),
        "keywords": find_orphan_keywords(user_id),
        "tags": find_orphan_tags(user_id),
    }


# ---- Orphan deletion -----------------------------------------------------

def _delete_records(items: list[Any]) -> int:
    for item in items:
        db.session.delete(item)
    return len(items)


def delete_all_orphans(user_id: int) -> dict[str, int]:
    """Delete orphaned rows in dependency order and re-scan after each stage."""
    counts: dict[str, int] = {}
    ordered_steps = (
        ("sources", find_orphan_sources, True),
        ("publishers", find_orphan_publishers, True),
        ("authors", find_orphan_authors, True),
        ("affiliations", find_orphan_affiliations, True),
        ("keywords", find_orphan_keywords, True),
        ("tags", find_orphan_tags, False),
    )

    for key, finder, should_flush in ordered_steps:
        counts[key] = _delete_records(finder(user_id))
        if should_flush:
            db.session.flush()

    db.session.commit()
    return counts


# ---- Targeted pruning after a single-document delete ---------------------

def prune_orphans_around_document(
    authors: Iterable[Author],
    keywords: Iterable[Keyword],
    tags: Iterable[Tag],
    source: Optional[Source],
) -> dict[str, int]:
    """Delete now-unreferenced entities related to a just-deleted document."""
    counts = {
        "keywords": 0,
        "tags": 0,
        "authors": 0,
        "affiliations": 0,
        "sources": 0,
        "publishers": 0,
        "author_codes": 0,
    }

    for kw in keywords:
        if not kw.documents:
            db.session.delete(kw)
            counts["keywords"] += 1

    for tag in tags:
        if not tag.documents:
            db.session.delete(tag)
            counts["tags"] += 1

    affs_to_check: set[Affiliation] = set()
    user_names_to_check: set[tuple[int, str]] = set()
    for author in authors:
        if author.document_links:
            continue
        affs_to_check.update(author.affiliations)
        user_names_to_check.add((author.user_id, author.name))
        db.session.delete(author)
        counts["authors"] += 1

    db.session.flush()

    for aff in affs_to_check:
        if not aff.authors:
            db.session.delete(aff)
            counts["affiliations"] += 1

    for uid, name in user_names_to_check:
        if Author.query.filter_by(user_id=uid, name=name).first():
            continue
        counter = db.session.get(AuthorCode, (uid, name))
        if counter is not None:
            db.session.delete(counter)
            counts["author_codes"] += 1

    publisher_to_check: Optional[Publisher] = None
    if source is not None and not source.documents:
        publisher_to_check = source.publisher
        db.session.delete(source)
        counts["sources"] += 1
        db.session.flush()

    if publisher_to_check is not None and not publisher_to_check.sources:
        db.session.delete(publisher_to_check)
        counts["publishers"] += 1

    return counts


# ---- Duplicate detection (display-only) ----------------------------------

def _normalize(name: str) -> str:
    return _WS.sub(" ", (name or "").strip().lower())


def _group_by_normalized_name(items: Iterable[Any]) -> list[list[Any]]:
    buckets: dict[str, list[Any]] = {}
    for item in items:
        key = _normalize(item.name)
        if key:
            buckets.setdefault(key, []).append(item)
    return [group for group in buckets.values() if len(group) > 1]


def _load_user_rows(model: Any, user_id: int) -> list[Any]:
    return model.query.filter_by(user_id=user_id).all()


def find_potential_duplicates(user_id: int) -> dict[str, list[list]]:
    return {
        "authors": _group_by_normalized_name(_load_user_rows(Author, user_id)),
        "affiliations": _group_by_normalized_name(_load_user_rows(Affiliation, user_id)),
        "publishers": _group_by_normalized_name(_load_user_rows(Publisher, user_id)),
        "sources": _group_by_normalized_name(_load_user_rows(Source, user_id)),
        "keywords": _group_by_normalized_name(_load_user_rows(Keyword, user_id)),
        "tags": _group_by_normalized_name(_load_user_rows(Tag, user_id)),
    }


# ---- Merge preview/apply/rollback ----------------------------------------

def _ordered_group(group: Iterable[Any]) -> tuple[Any, list[Any]]:
    ordered = sorted(group, key=lambda item: item.id)
    return ordered[0], ordered[1:]


def _build_plan_entry(
    canonical: Any,
    aliases: list[Any],
    impacted_docs: int,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "canonical_id": canonical.id,
        "canonical_name": canonical.name,
        "alias_ids": [alias.id for alias in aliases],
        "alias_names": [alias.name for alias in aliases],
        "impacted_docs": impacted_docs,
        **extra,
    }


def _count_distinct(query) -> int:
    return query.distinct().count()


def _build_plan_from_groups(
    groups: Iterable[list[Any]],
    impact_counter: Callable[[list[Any]], int],
    **extra_factory: Callable[[Any], Any] | Any,
) -> list[dict[str, Any]]:
    plan_items: list[dict[str, Any]] = []
    for group in groups:
        canonical, aliases = _ordered_group(group)
        if not aliases:
            continue
        extra_values = {
            key: value(canonical) if callable(value) else value
            for key, value in extra_factory.items()
        }
        plan_items.append(
            _build_plan_entry(canonical, aliases, impact_counter(aliases), **extra_values)
        )
    return plan_items


def _source_duplicate_groups(user_id: int) -> list[list[Source]]:
    buckets: dict[tuple[str, str], list[Source]] = {}
    for src in _load_user_rows(Source, user_id):
        key = (_normalize(src.name), src.type)
        if key[0]:
            buckets.setdefault(key, []).append(src)
    return [group for group in buckets.values() if len(group) > 1]


def _build_merge_plan(user_id: int) -> dict[str, list[dict]]:
    groups = find_potential_duplicates(user_id)
    return {
        "authors": _build_plan_from_groups(
            groups["authors"],
            lambda aliases: _count_distinct(
                db.session.query(DocumentAuthor.document_id).filter(
                    DocumentAuthor.author_id.in_([alias.id for alias in aliases])
                )
            ),
        ),
        "affiliations": _build_plan_from_groups(
            groups["affiliations"],
            lambda aliases: _count_distinct(
                db.session.query(AuthorAffiliation.author_id).filter(
                    AuthorAffiliation.affiliation_id.in_([alias.id for alias in aliases])
                )
            ),
        ),
        "publishers": _build_plan_from_groups(
            groups["publishers"],
            lambda aliases: _count_distinct(
                db.session.query(Document.id)
                .join(Source, Document.source_id == Source.id)
                .filter(Source.publisher_id.in_([alias.id for alias in aliases]))
            ),
        ),
        "sources": _build_plan_from_groups(
            _source_duplicate_groups(user_id),
            lambda aliases: _count_distinct(
                db.session.query(Document.id).filter(
                    Document.source_id.in_([alias.id for alias in aliases])
                )
            ),
            source_type=lambda canonical: canonical.type,
        ),
        "keywords": _build_plan_from_groups(
            groups["keywords"],
            lambda aliases: _count_distinct(
                db.session.query(DocumentKeyword.document_id).filter(
                    DocumentKeyword.keyword_id.in_([alias.id for alias in aliases])
                )
            ),
        ),
        "tags": _build_plan_from_groups(
            groups["tags"],
            lambda aliases: _count_distinct(
                db.session.query(DocumentTag.document_id).filter(
                    DocumentTag.tag_id.in_([alias.id for alias in aliases])
                )
            ),
        ),
    }


def _summarize_plan(plan: dict[str, list[dict]]) -> dict[str, int]:
    return {
        "groups": sum(len(items) for items in plan.values()),
        "aliases": sum(len(item["alias_ids"]) for items in plan.values() for item in items),
        "impacted_docs": sum(item["impacted_docs"] for items in plan.values() for item in items),
    }


def merge_preview(user_id: int) -> dict:
    plan = _build_merge_plan(user_id)
    return {"plan": plan, "summary": _summarize_plan(plan)}


def _append_deleted(audit: dict[str, list], model: str, obj: Any, payload: dict[str, Any]) -> None:
    audit["deleted"].append({"model": model, "id": obj.id, "payload": payload})


def _apply_author_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for link in DocumentAuthor.query.filter_by(author_id=alias_id).all():
            existing = DocumentAuthor.query.filter_by(
                document_id=link.document_id,
                author_id=canonical_id,
            ).first()
            if existing:
                audit["doc_author_deleted"].append(
                    {
                        "document_id": link.document_id,
                        "author_id": alias_id,
                        "author_order": link.author_order,
                    }
                )
                db.session.delete(link)
            else:
                audit["doc_author_updates"].append(
                    {
                        "document_id": link.document_id,
                        "from_author_id": alias_id,
                        "to_author_id": canonical_id,
                    }
                )
                link.author_id = canonical_id
            changed += 1

        for link in AuthorAffiliation.query.filter_by(author_id=alias_id).all():
            existing = AuthorAffiliation.query.filter_by(
                author_id=canonical_id,
                affiliation_id=link.affiliation_id,
            ).first()
            if existing:
                audit["author_aff_deleted"].append(
                    {"author_id": alias_id, "affiliation_id": link.affiliation_id}
                )
                db.session.delete(link)
            else:
                audit["author_aff_updates"].append(
                    {
                        "from_author_id": alias_id,
                        "to_author_id": canonical_id,
                        "affiliation_id": link.affiliation_id,
                    }
                )
                link.author_id = canonical_id

        alias_obj = db.session.get(Author, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "author",
                alias_obj,
                {"name": alias_obj.name, "code": alias_obj.code},
            )
            db.session.delete(alias_obj)
    return changed


def _apply_affiliation_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for link in AuthorAffiliation.query.filter_by(affiliation_id=alias_id).all():
            existing = AuthorAffiliation.query.filter_by(
                author_id=link.author_id,
                affiliation_id=canonical_id,
            ).first()
            if existing:
                audit["author_aff_deleted"].append(
                    {"author_id": link.author_id, "affiliation_id": alias_id}
                )
                db.session.delete(link)
            else:
                audit["author_aff_updates"].append(
                    {
                        "author_id": link.author_id,
                        "from_affiliation_id": alias_id,
                        "to_affiliation_id": canonical_id,
                    }
                )
                link.affiliation_id = canonical_id
            changed += 1

        alias_obj = db.session.get(Affiliation, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "affiliation",
                alias_obj,
                {"name": alias_obj.name},
            )
            db.session.delete(alias_obj)
    return changed


def _apply_publisher_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for src in Source.query.filter_by(publisher_id=alias_id).all():
            audit["source_publisher_updates"].append(
                {
                    "source_id": src.id,
                    "from_publisher_id": alias_id,
                    "to_publisher_id": canonical_id,
                }
            )
            src.publisher_id = canonical_id
            changed += 1

        alias_obj = db.session.get(Publisher, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "publisher",
                alias_obj,
                {"name": alias_obj.name},
            )
            db.session.delete(alias_obj)
    return changed


def _apply_source_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for doc in Document.query.filter_by(source_id=alias_id).all():
            audit["doc_source_updates"].append(
                {
                    "document_id": doc.id,
                    "from_source_id": alias_id,
                    "to_source_id": canonical_id,
                }
            )
            doc.source_id = canonical_id
            changed += 1

        alias_obj = db.session.get(Source, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "source",
                alias_obj,
                {
                    "name": alias_obj.name,
                    "type": alias_obj.type,
                    "publisher_id": alias_obj.publisher_id,
                },
            )
            db.session.delete(alias_obj)
    return changed


def _apply_keyword_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for link in DocumentKeyword.query.filter_by(keyword_id=alias_id).all():
            existing = DocumentKeyword.query.filter_by(
                document_id=link.document_id,
                keyword_id=canonical_id,
            ).first()
            if existing:
                audit["doc_keyword_deleted"].append(
                    {"document_id": link.document_id, "keyword_id": alias_id}
                )
                db.session.delete(link)
            else:
                audit["doc_keyword_updates"].append(
                    {
                        "document_id": link.document_id,
                        "from_keyword_id": alias_id,
                        "to_keyword_id": canonical_id,
                    }
                )
                link.keyword_id = canonical_id
            changed += 1

        alias_obj = db.session.get(Keyword, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "keyword",
                alias_obj,
                {"name": alias_obj.name},
            )
            db.session.delete(alias_obj)
    return changed


def _apply_tag_group(canonical_id: int, alias_ids: list[int], audit: dict[str, list]) -> int:
    changed = 0
    for alias_id in alias_ids:
        for link in DocumentTag.query.filter_by(tag_id=alias_id).all():
            existing = DocumentTag.query.filter_by(
                document_id=link.document_id,
                tag_id=canonical_id,
            ).first()
            if existing:
                audit["doc_tag_deleted"].append(
                    {"document_id": link.document_id, "tag_id": alias_id}
                )
                db.session.delete(link)
            else:
                audit["doc_tag_updates"].append(
                    {
                        "document_id": link.document_id,
                        "from_tag_id": alias_id,
                        "to_tag_id": canonical_id,
                    }
                )
                link.tag_id = canonical_id
            changed += 1

        alias_obj = db.session.get(Tag, alias_id)
        if alias_obj is not None:
            _append_deleted(
                audit,
                "tag",
                alias_obj,
                {"name": alias_obj.name},
            )
            db.session.delete(alias_obj)
    return changed


def _new_audit_payload(user_id: int, plan: dict[str, list[dict]]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "plan": deepcopy(plan),
        "deleted": [],
        "doc_author_updates": [],
        "doc_author_deleted": [],
        "author_aff_updates": [],
        "author_aff_deleted": [],
        "source_publisher_updates": [],
        "doc_source_updates": [],
        "doc_keyword_updates": [],
        "doc_keyword_deleted": [],
        "doc_tag_updates": [],
        "doc_tag_deleted": [],
    }


def merge_apply(user_id: int) -> dict:
    plan = _build_merge_plan(user_id)
    audit = _new_audit_payload(user_id, plan)
    affected = 0

    appliers = {
        "authors": _apply_author_group,
        "affiliations": _apply_affiliation_group,
        "publishers": _apply_publisher_group,
        "sources": _apply_source_group,
        "keywords": _apply_keyword_group,
        "tags": _apply_tag_group,
    }
    for key in PLAN_KEYS:
        for item in plan[key]:
            affected += appliers[key](item["canonical_id"], item["alias_ids"], audit)

    summary = {
        "groups_merged": sum(len(items) for items in plan.values()),
        "aliases_merged": sum(
            len(item["alias_ids"]) for items in plan.values() for item in items
        ),
        "records_relinked": affected,
    }
    audit_row = MergeAudit(
        user_id=user_id,
        action="merge_apply",
        summary_json=json.dumps(summary, ensure_ascii=False),
        payload_json=json.dumps(audit, ensure_ascii=False),
    )
    db.session.add(audit_row)
    db.session.commit()
    return {"ok": True, **summary, "audit_id": audit_row.id}


def _restore_deleted_row(user_id: int, deleted: dict[str, Any]) -> None:
    model = deleted["model"]
    payload = deleted["payload"]
    if model == "author":
        obj = Author(
            id=deleted["id"],
            user_id=user_id,
            name=payload["name"],
            code=payload["code"],
        )
    elif model == "affiliation":
        obj = Affiliation(id=deleted["id"], user_id=user_id, name=payload["name"])
    elif model == "publisher":
        obj = Publisher(id=deleted["id"], user_id=user_id, name=payload["name"])
    elif model == "source":
        obj = Source(
            id=deleted["id"],
            user_id=user_id,
            name=payload["name"],
            type=payload["type"],
            publisher_id=payload["publisher_id"],
        )
    elif model == "keyword":
        obj = Keyword(id=deleted["id"], user_id=user_id, name=payload["name"])
    elif model == "tag":
        obj = Tag(id=deleted["id"], user_id=user_id, name=payload["name"])
    else:
        return
    db.session.merge(obj)


def _ensure_document_keyword(document_id: int, keyword_id: int) -> None:
    exists = DocumentKeyword.query.filter_by(
        document_id=document_id,
        keyword_id=keyword_id,
    ).first()
    if not exists:
        db.session.add(DocumentKeyword(document_id=document_id, keyword_id=keyword_id))


def _ensure_document_tag(document_id: int, tag_id: int) -> None:
    exists = DocumentTag.query.filter_by(
        document_id=document_id,
        tag_id=tag_id,
    ).first()
    if not exists:
        db.session.add(DocumentTag(document_id=document_id, tag_id=tag_id))


def _ensure_author_affiliation(author_id: int, affiliation_id: int) -> None:
    exists = AuthorAffiliation.query.filter_by(
        author_id=author_id,
        affiliation_id=affiliation_id,
    ).first()
    if not exists:
        db.session.add(
            AuthorAffiliation(author_id=author_id, affiliation_id=affiliation_id)
        )


def _ensure_document_author(document_id: int, author_id: int, author_order: int) -> None:
    exists = DocumentAuthor.query.filter_by(
        document_id=document_id,
        author_id=author_id,
    ).first()
    if not exists:
        db.session.add(
            DocumentAuthor(
                document_id=document_id,
                author_id=author_id,
                author_order=author_order,
            )
        )


def _rollback_source_changes(audit: dict[str, Any]) -> None:
    for change in audit["doc_source_updates"]:
        doc = db.session.get(Document, change["document_id"])
        if doc is not None:
            doc.source_id = change["from_source_id"]

    for change in audit["source_publisher_updates"]:
        src = db.session.get(Source, change["source_id"])
        if src is not None:
            src.publisher_id = change["from_publisher_id"]


def _rollback_keyword_changes(audit: dict[str, Any]) -> None:
    for change in audit["doc_keyword_updates"]:
        link = DocumentKeyword.query.filter_by(
            document_id=change["document_id"],
            keyword_id=change["to_keyword_id"],
        ).first()
        if link is not None:
            link.keyword_id = change["from_keyword_id"]

    for change in audit["doc_keyword_deleted"]:
        _ensure_document_keyword(change["document_id"], change["keyword_id"])


def _rollback_tag_changes(audit: dict[str, Any]) -> None:
    for change in audit.get("doc_tag_updates", []):
        link = DocumentTag.query.filter_by(
            document_id=change["document_id"],
            tag_id=change["to_tag_id"],
        ).first()
        if link is not None:
            link.tag_id = change["from_tag_id"]

    for change in audit.get("doc_tag_deleted", []):
        _ensure_document_tag(change["document_id"], change["tag_id"])


def _rollback_author_affiliation_changes(audit: dict[str, Any]) -> None:
    for change in audit["author_aff_updates"]:
        if "from_affiliation_id" in change:
            link = AuthorAffiliation.query.filter_by(
                author_id=change["author_id"],
                affiliation_id=change["to_affiliation_id"],
            ).first()
            if link is not None:
                link.affiliation_id = change["from_affiliation_id"]
            continue

        link = AuthorAffiliation.query.filter_by(
            author_id=change["to_author_id"],
            affiliation_id=change["affiliation_id"],
        ).first()
        if link is not None:
            link.author_id = change["from_author_id"]

    for change in audit["author_aff_deleted"]:
        _ensure_author_affiliation(change["author_id"], change["affiliation_id"])


def _rollback_document_author_changes(audit: dict[str, Any]) -> None:
    for change in audit["doc_author_updates"]:
        link = DocumentAuthor.query.filter_by(
            document_id=change["document_id"],
            author_id=change["to_author_id"],
        ).first()
        if link is not None:
            link.author_id = change["from_author_id"]

    for change in audit["doc_author_deleted"]:
        _ensure_document_author(
            change["document_id"],
            change["author_id"],
            change["author_order"],
        )


def _rollback_from_audit_row(user_id: int, row: MergeAudit) -> dict:
    audit = json.loads(row.payload_json or "{}")
    if not audit:
        return {"ok": False, "error": "invalid_audit_payload"}

    for deleted in audit["deleted"]:
        _restore_deleted_row(user_id, deleted)
    db.session.flush()

    _rollback_source_changes(audit)
    _rollback_keyword_changes(audit)
    _rollback_tag_changes(audit)
    _rollback_author_affiliation_changes(audit)
    _rollback_document_author_changes(audit)

    row.rolled_back_at = datetime.now(timezone.utc)
    rb_row = MergeAudit(
        user_id=user_id,
        action="merge_rollback",
        target_audit_id=row.id,
        summary_json=json.dumps({"rollback_of": row.id}, ensure_ascii=False),
        payload_json=json.dumps({"target_audit_id": row.id}, ensure_ascii=False),
    )
    db.session.add(rb_row)
    db.session.commit()
    return {"ok": True, "rolled_back_audit_id": row.id, "rollback_audit_id": rb_row.id}


def _find_open_merge_audit(user_id: int) -> Optional[MergeAudit]:
    return (
        MergeAudit.query.filter_by(
            user_id=user_id,
            action="merge_apply",
            rolled_back_at=None,
        )
        .order_by(MergeAudit.id.desc())
        .first()
    )


def merge_rollback_last(user_id: int) -> dict:
    row = _find_open_merge_audit(user_id)
    if not row:
        return {"ok": False, "error": "no_last_merge"}
    return _rollback_from_audit_row(user_id, row)


def merge_rollback_by_audit_id(user_id: int, audit_id: int) -> dict:
    row = MergeAudit.query.filter_by(
        id=audit_id,
        user_id=user_id,
        action="merge_apply",
    ).first()
    if not row:
        return {"ok": False, "error": "audit_not_found"}
    if row.rolled_back_at is not None:
        return {"ok": False, "error": "already_rolled_back"}
    return _rollback_from_audit_row(user_id, row)


def list_merge_audits(user_id: int, limit: int = 20) -> list[dict]:
    rows = (
        MergeAudit.query.filter_by(user_id=user_id)
        .order_by(MergeAudit.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    audits = []
    for row in rows:
        try:
            summary = json.loads(row.summary_json or "{}")
        except Exception:
            summary = {}
        audits.append(
            {
                "id": row.id,
                "action": row.action,
                "target_audit_id": row.target_audit_id,
                "rolled_back_at": row.rolled_back_at.isoformat() if row.rolled_back_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "summary": summary,
            }
        )
    return audits
