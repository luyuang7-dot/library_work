"""Batch PDF recognition and batch import endpoints."""

from __future__ import annotations

import os
import time

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Category, Document, DocumentAuthor, UserSetting
from ..services import bibtex_io, mineru_client, pdf_metadata, upsert
from ..services.ai_agent import record_activity
from ..services.file_io import save_uploaded_files

bp = Blueprint("batch_bibtex", __name__)

_ALLOWED_ATTACHMENT_EXTS = {"pdf"}


def _is_pdf(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[-1].lower() in _ALLOWED_ATTACHMENT_EXTS


def _get_mineru_url(user_id: int) -> str:
    setting = db.session.get(UserSetting, user_id)
    return (
        (setting.mineru_url if setting and setting.mineru_url else "").strip()
        or current_app.config.get("DEFAULT_MINERU_URL", "http://127.0.0.1:8000")
    )


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _resolve_category_id(
    raw_category_id: int | None,
    fallback_category_id: int | None,
    user_id: int,
) -> int | None:
    category_id = raw_category_id or fallback_category_id
    if not category_id:
        return None
    category = Category.query.filter_by(id=category_id, user_id=user_id).first()
    return category.id if category else None


def _append_unique_keywords(document: Document, names: list[str], user_id: int) -> None:
    existing = {keyword.name for keyword in document.keywords}
    for name in names:
        if name in existing:
            continue
        document.keywords.append(upsert.get_or_create_keyword(name, user_id))
        existing.add(name)


def _append_unique_tags(document: Document, names: list[str], user_id: int) -> None:
    existing = {tag.name for tag in document.tags}
    for name in names:
        if name in existing:
            continue
        document.tags.append(upsert.get_or_create_tag(name, user_id))
        existing.add(name)


def _persist_batch_form(form, user_id: int) -> dict:
    title = _trim(form.get("title"))
    if not title:
        return {"created": None, "skipped_reason": "missing_title"}

    doi = _trim(form.get("doi")) or None
    year_raw = _trim(form.get("publication_year"))
    try:
        publication_year = int(year_raw) if year_raw else None
    except ValueError:
        publication_year = None

    existing = None
    if doi:
        existing = Document.query.filter_by(user_id=user_id, doi=doi).first()
    if not existing:
        existing = Document.query.filter_by(
            user_id=user_id,
            title=title,
            publication_year=publication_year,
        ).first()
    if existing:
        return {
            "created": None,
            "skipped_reason": f"existing_document:{existing.id}:{existing.title}",
        }

    document_type = _trim(form.get("document_type")) or "journal_article"
    source_name = _trim(form.get("source_name"))
    source_type = _trim(form.get("source_type")) or "journal"
    publisher_name = _trim(form.get("publisher_name"))
    category_id = _resolve_category_id(
        form.get("category_id", type=int),
        form.get("default_category_id", type=int),
        user_id,
    )

    document = Document(
        user_id=user_id,
        title=title,
        abstract=_trim(form.get("abstract")) or None,
        document_type=document_type,
        publication_year=publication_year,
        volume=_trim(form.get("volume")) or None,
        issue=_trim(form.get("issue")) or None,
        pages=_trim(form.get("pages")) or None,
        doi=doi,
        notes=_trim(form.get("notes")) or None,
        reading_status=_trim(form.get("reading_status")) or "unread",
        category_id=category_id,
        source=upsert.get_or_create_source(
            source_name,
            user_id,
            source_type,
            publisher_name,
        ),
    )
    db.session.add(document)
    db.session.flush()

    seen_author_ids: set[int] = set()
    order = 0
    for entry in upsert.parse_authors_field(form.get("authors_raw", "")):
        code_marker = entry["code"]
        if code_marker == "new":
            author = upsert.allocate_new_author(entry["name"], user_id)
        elif isinstance(code_marker, int):
            author = upsert.get_or_create_author(entry["name"], user_id, code=code_marker)
        else:
            author = upsert.get_or_create_author_lenient(entry["name"], user_id)
        if author.id in seen_author_ids:
            continue
        seen_author_ids.add(author.id)
        order += 1
        for affiliation_name in entry["affiliations"]:
            affiliation = upsert.get_or_create_affiliation(affiliation_name, user_id)
            if affiliation not in author.affiliations:
                author.affiliations.append(affiliation)
        db.session.add(
            DocumentAuthor(
                document_id=document.id,
                author_id=author.id,
                author_order=order,
            )
        )

    _append_unique_keywords(
        document,
        upsert.parse_csv_list(form.get("keywords_raw", "")),
        user_id,
    )
    _append_unique_tags(
        document,
        upsert.parse_csv_list(form.get("tags_raw", "")),
        user_id,
    )

    return {"created": document, "skipped_reason": None}


@bp.route("/batch", methods=["GET"])
@login_required
def batch_page():
    uid = current_user.id
    categories = Category.query.filter_by(user_id=uid).order_by(Category.name).all()
    categories_payload = [{"id": c.id, "name": c.name} for c in categories]
    latest_doc = Document.query.order_by(Document.id.desc()).first()
    next_doc_id = (latest_doc.id if latest_doc else 0) + 1
    supported_types = bibtex_io.supported_entry_types()
    return render_template(
        "bibtex/batch.html",
        categories=categories_payload,
        mineru_url=_get_mineru_url(uid),
        next_doc_id=next_doc_id,
        supported_types=supported_types,
    )


@bp.route("/batch/recognize", methods=["POST"])
@login_required
def recognize():
    file = request.files.get("pdf")
    if not file or not file.filename:
        return jsonify(ok=False, error="缺少 PDF 文件。"), 400
    if not _is_pdf(file.filename):
        return jsonify(ok=False, error="仅支持 PDF 文件。"), 400

    file_bytes = file.read()
    if not file_bytes:
        return jsonify(ok=False, error="上传的 PDF 为空。"), 400

    try:
        parsed = mineru_client.parse_pdf(
            _get_mineru_url(current_user.id),
            file_bytes,
            file.filename,
            backend="pipeline",
        )
    except mineru_client.MineruError as exc:
        return jsonify(ok=False, error=str(exc)), 502

    metadata = pdf_metadata.extract_metadata(parsed)
    record_activity(
        current_user.id,
        "pdf_recognize",
        "Batch recognize PDF",
        {"filename": file.filename},
    )
    return jsonify(
        ok=True,
        filename=file.filename,
        markdown=parsed.get("md", ""),
        suggested_fields={
            "title": metadata.get("title", ""),
            "authors": metadata.get("authors", []),
            "abstract": metadata.get("abstract", ""),
            "keywords": metadata.get("keywords", []),
            "doi": metadata.get("doi", ""),
            "year": metadata.get("year"),
            "source": metadata.get("source", ""),
        },
    )


@bp.route("/batch/import", methods=["POST"])
@login_required
def import_one():
    file = request.files.get("pdf")
    if not file or not file.filename:
        return jsonify(ok=False, error="缺少 PDF 文件。"), 400
    if not _is_pdf(file.filename):
        return jsonify(ok=False, error="仅支持 PDF 文件。"), 400

    uid = current_user.id
    try:
        result = _persist_batch_form(request.form, uid)
    except Exception as exc:
        db.session.rollback()
        return jsonify(ok=False, reason="save_failed", error_detail=str(exc))

    if result["skipped_reason"]:
        db.session.rollback()
        reason = result["skipped_reason"]
        if reason == "missing_title":
            return jsonify(ok=False, reason="missing_title", error_detail="标题不能为空。")
        if reason.startswith("existing_document:"):
            _, doc_id, title = reason.split(":", 2)
            return jsonify(
                ok=False,
                reason="duplicate",
                error_detail=f"检测到重复文献：#{doc_id}《{title}》。",
            )
        return jsonify(ok=False, reason="duplicate", error_detail="检测到重复文献。")

    document = result["created"]
    saved_paths = []
    try:
        saved_paths, _ = save_uploaded_files(document, [file], uid)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        try:
            file.close()
        except Exception:
            pass
        cleanup_errors = []
        for path in saved_paths:
            try:
                for _ in range(10):
                    try:
                        path.unlink(missing_ok=True)
                        if path.exists():
                            os.remove(path)
                        break
                    except PermissionError:
                        time.sleep(0.05)
                if path.exists():
                    raise PermissionError(f"failed to unlink {path}")
            except Exception as unlink_error:
                cleanup_errors.append(f"{path}: {unlink_error}")
        detail = str(exc)
        if cleanup_errors:
            detail += " | cleanup_errors=" + "; ".join(cleanup_errors)
        return jsonify(ok=False, reason="save_failed", error_detail=detail)

    record_activity(
        current_user.id,
        "batch_document_import",
        "Batch import PDF + form",
        {"document_id": document.id, "filename": file.filename},
    )
    return jsonify(ok=True, document_id=document.id, title=document.title)


@bp.route("/batch/health", methods=["GET"])
@login_required
def batch_health():
    base_url = _get_mineru_url(current_user.id)
    try:
        info = mineru_client.health_check(base_url)
    except mineru_client.MineruError as exc:
        return jsonify(ok=False, error=str(exc), url=base_url)
    return jsonify(ok=True, info=info, url=base_url)
