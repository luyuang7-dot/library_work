from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    Author,
    AuthorCode,
    Category,
    Document,
    DocumentAuthor,
    DocumentTag,
    File,
    Keyword,
    Source,
    Tag,
    UserSetting,
)
from ..services import dict_cleanup, mineru_client, pdf_metadata, upsert
from ..services.ai_agent import record_activity
from ..services.file_io import save_uploaded_files as _save_uploaded_files_impl

bp = Blueprint("documents", __name__)
DOCUMENTS_PER_PAGE = 20


def _expand_category_ids(root_id: int, user_id: int) -> list[int]:
    cats = Category.query.filter_by(user_id=user_id).all()
    by_parent: dict[int | None, list[int]] = {}
    for category in cats:
        by_parent.setdefault(category.parent_id, []).append(category.id)

    found: set[int] = set()
    stack = [root_id]
    while stack:
        cid = stack.pop()
        if cid in found:
            continue
        found.add(cid)
        stack.extend(by_parent.get(cid, []))
    return list(found)


def _ordered_categories(user_id: int) -> list[Category]:
    cats = Category.query.filter_by(user_id=user_id).order_by(Category.name).all()
    by_parent: dict[int | None, list[Category]] = {}
    for category in cats:
        by_parent.setdefault(category.parent_id, []).append(category)

    ordered: list[Category] = []

    def visit(parent_id: int | None, depth: int) -> None:
        for category in by_parent.get(parent_id, []):
            category.depth = depth
            ordered.append(category)
            visit(category.id, depth + 1)

    visit(None, 0)
    return ordered


def _save_uploaded_files(document: Document, files) -> None:
    _, skipped = _save_uploaded_files_impl(document, files, current_user.id)
    for name in skipped:
        flash(f"已跳过不支持的附件类型：{name}", "warning")


def _persist_document_form(document: Document, form, files=None) -> None:
    document.title = form.get("title", "").strip()
    document.abstract = form.get("abstract") or None
    document.document_type = form.get("document_type") or "journal_article"
    document.publication_year = (
        int(form["publication_year"]) if form.get("publication_year") else None
    )
    document.volume = form.get("volume") or None
    document.issue = form.get("issue") or None
    document.pages = form.get("pages") or None
    document.doi = form.get("doi") or None
    document.notes = form.get("notes") or None
    document.rating = int(form["rating"]) if form.get("rating") else None
    document.reading_status = form.get("reading_status") or "unread"
    document.barcode = (form.get("barcode") or "").strip() or None
    document.copy_no = (form.get("copy_no") or "").strip() or None

    category_id = form.get("category_id")
    if category_id:
        document.category = Category.query.filter_by(
            id=int(category_id),
            user_id=current_user.id,
        ).first()
    else:
        document.category = None

    user_id = current_user.id
    source_name = (form.get("source_name") or "").strip()
    source_type = form.get("source_type") or "journal"
    publisher_name = (form.get("publisher_name") or "").strip()
    document.source = upsert.get_or_create_source(
        source_name,
        user_id,
        source_type,
        publisher_name,
    )

    parsed_authors = upsert.parse_authors_field(form.get("authors_raw", ""))
    seen_pairs: set[tuple[str, object]] = set()
    deduped_authors = []
    for entry in parsed_authors:
        key = (entry["name"], entry["code"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        deduped_authors.append(entry)

    if len(deduped_authors) < len(parsed_authors):
        flash(
            f"已自动移除 {len(parsed_authors) - len(deduped_authors)} 条重复作者记录。",
            "info",
        )
    parsed_authors = deduped_authors

    document.author_links.clear()
    db.session.flush()
    seen_author_ids: set[int] = set()
    order = 0
    for entry in parsed_authors:
        code_marker = entry["code"]
        if code_marker == "new":
            author = upsert.allocate_new_author(entry["name"], user_id)
        elif isinstance(code_marker, int):
            author = upsert.get_or_create_author(
                entry["name"],
                user_id,
                code=code_marker,
            )
        else:
            author = upsert.get_or_create_author(entry["name"], user_id)

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

    document.keywords.clear()
    raw_keywords = upsert.parse_csv_list(form.get("keywords_raw", ""))
    deduped_keywords = list(dict.fromkeys(raw_keywords))
    if len(deduped_keywords) < len(raw_keywords):
        flash(
            f"已自动移除 {len(raw_keywords) - len(deduped_keywords)} 个重复关键词。",
            "info",
        )
    for keyword_name in deduped_keywords:
        document.keywords.append(upsert.get_or_create_keyword(keyword_name, user_id))

    document.tags.clear()
    raw_tags = upsert.parse_csv_list(form.get("tags_raw", ""))
    deduped_tags = list(dict.fromkeys(raw_tags))
    if len(deduped_tags) < len(raw_tags):
        flash(
            f"已自动移除 {len(raw_tags) - len(deduped_tags)} 个重复标签。",
            "info",
        )
    for tag_name in deduped_tags:
        document.tags.append(upsert.get_or_create_tag(tag_name, user_id))

    if files:
        _save_uploaded_files(document, files)


def _delete_document_and_collect_cleanup(doc: Document) -> dict[str, int]:
    related_authors = {link.author for link in doc.author_links}
    related_keywords = set(doc.keywords)
    related_tags = set(doc.tags)
    related_source = doc.source

    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    for file_record in doc.files:
        try:
            (upload_root / file_record.file_path).unlink(missing_ok=True)
        except Exception:
            pass

    db.session.delete(doc)
    db.session.flush()

    return dict_cleanup.prune_orphans_around_document(
        related_authors,
        related_keywords,
        related_tags,
        related_source,
    )


def _cleanup_summary_text(cleaned: dict[str, int]) -> str:
    labels = {
        "keywords": "keywords",
        "tags": "tags",
        "authors": "authors",
        "affiliations": "affiliations",
        "sources": "sources",
        "publishers": "publishers",
    }
    parts = [
        f"{value} {labels[key]}"
        for key, value in cleaned.items()
        if key in labels and value
    ]
    return f" (cleanup: {', '.join(parts)})" if parts else ""


def _parse_bulk_doc_ids(form) -> list[int]:
    doc_ids: list[int] = []
    for raw in form.getlist("doc_ids"):
        try:
            doc_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return doc_ids


def _list_redirect_params_from_form(form) -> dict[str, str]:
    redirect_params: dict[str, str] = {}
    for name in ("page", "category"):
        value = (form.get(f"return_{name}") or "").strip()
        if value:
            redirect_params[name] = value
    return redirect_params


def _selected_documents_or_redirect():
    doc_ids = _parse_bulk_doc_ids(request.form)
    redirect_params = _list_redirect_params_from_form(request.form)
    if not doc_ids:
        flash("请先选择至少一篇文献。", "warning")
        return None, redirect(url_for("documents.list_documents", **redirect_params))

    documents = (
        Document.query.filter(
            Document.user_id == current_user.id,
            Document.id.in_(doc_ids),
        )
        .order_by(Document.id.asc())
        .all()
    )
    if not documents:
        flash("没有找到可操作的文献。", "warning")
        return None, redirect(url_for("documents.list_documents", **redirect_params))
    return documents, None


def _build_combined_markdown(filename: str, meta: dict, raw_md: str) -> str:
    def _or(value, fallback="-"):
        if value in (None, "", []):
            return fallback
        return value

    title = _or(meta.get("title"))
    authors = meta.get("authors") or []
    affiliations = meta.get("affiliations") or []
    emails = meta.get("emails") or []
    keywords = meta.get("keywords") or []
    abstract = (meta.get("abstract") or "").strip()
    doi = _or(meta.get("doi"))
    year = _or(meta.get("year"))
    source = _or(meta.get("source"))
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# 识别结果 - {filename}",
        "",
        f"> 由 MinerU 于 {timestamp} 生成",
        "",
        "## 建议元数据",
        "",
        f"- 标题：{title}",
        f"- 作者：{', '.join(authors) if authors else '-'}",
        f"- 邮箱：{', '.join(emails) if emails else '-'}",
        f"- 单位：{'; '.join(affiliations) if affiliations else '-'}",
        f"- DOI: {doi}",
        f"- 年份：{year}",
        f"- 来源：{source}",
        f"- 关键词：{', '.join(keywords) if keywords else '-'}",
        "",
        "### 摘要",
        "",
        abstract or "-",
        "",
        "---",
        "",
        "## MinerU 原始 Markdown",
        "",
        raw_md or "*(MinerU 未返回 Markdown 内容)*",
        "",
    ]
    return "\n".join(lines)


def _get_mineru_url(user_id: int) -> str:
    setting = db.session.get(UserSetting, user_id)
    default_url = current_app.config.get("DEFAULT_MINERU_URL", "http://127.0.0.1:8000")
    return (
        (setting.mineru_url if setting and setting.mineru_url else "").strip()
        or default_url
    )


@bp.route("/")
@login_required
def list_documents():
    category_id = request.args.get("category", type=int)

    query = Document.query.filter_by(user_id=current_user.id)
    if category_id:
        expanded_ids = _expand_category_ids(category_id, current_user.id)
        query = query.filter(Document.category_id.in_(expanded_ids))

    page = request.args.get("page", 1, type=int) or 1
    pagination = query.order_by(Document.updated_at.desc()).paginate(
        page=page,
        per_page=DOCUMENTS_PER_PAGE,
        error_out=False,
    )
    documents = pagination.items
    categories = _ordered_categories(current_user.id)
    active_category_name = None
    if category_id:
        category = Category.query.filter_by(
            id=category_id,
            user_id=current_user.id,
        ).first()
        active_category_name = category.name if category else None

    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop("page", None)

    def page_url(page_number: int) -> str:
        return url_for("documents.list_documents", page=page_number, **pagination_args)

    return render_template(
        "documents/list.html",
        documents=documents,
        pagination=pagination,
        page_url=page_url,
        categories=categories,
        active_category=category_id,
        active_category_name=active_category_name,
    )


@bp.route("/search")
@login_required
def search():
    uid = current_user.id
    q = (request.args.get("q") or "").strip()
    author = (request.args.get("author") or "").strip()
    source = (request.args.get("source") or "").strip()
    category_id = request.args.get("category", type=int)
    doc_type = request.args.get("type")
    year = request.args.get("year", type=int)
    year_from = request.args.get("year_from", type=int)
    year_to = request.args.get("year_to", type=int)
    reading_status = request.args.get("reading_status")
    rating_min = request.args.get("rating_min", type=int)
    selected_tag_ids = [tid for tid in request.args.getlist("tags", type=int) if tid]

    base = Document.query.filter_by(user_id=uid)
    if q:
        like = f"%{q}%"
        base = base.filter(
            or_(
                Document.title.ilike(like),
                Document.abstract.ilike(like),
                Document.doi.ilike(like),
                Document.author_links.any(
                    DocumentAuthor.author.has(Author.name.ilike(like))
                ),
                Document.keywords.any(Keyword.name.ilike(like)),
                Document.tags.any(Tag.name.ilike(like)),
                Document.source.has(Source.name.ilike(like)),
            )
        )
    if author:
        base = base.filter(
            Document.author_links.any(
                DocumentAuthor.author.has(Author.name.ilike(f"%{author}%"))
            )
        )
    if source:
        base = base.filter(Document.source.has(Source.name.ilike(f"%{source}%")))
    if category_id:
        base = base.filter(Document.category_id.in_(_expand_category_ids(category_id, uid)))
    if doc_type:
        base = base.filter_by(document_type=doc_type)
    if year:
        base = base.filter_by(publication_year=year)
    if year_from:
        base = base.filter(Document.publication_year >= year_from)
    if year_to:
        base = base.filter(Document.publication_year <= year_to)
    if reading_status in {"unread", "reading", "read"}:
        base = base.filter_by(reading_status=reading_status)
    if rating_min:
        base = base.filter(Document.rating >= rating_min)

    if selected_tag_ids:
        match_count = func.count(func.distinct(DocumentTag.tag_id))
        rows = (
            base.join(DocumentTag, DocumentTag.document_id == Document.id)
            .filter(DocumentTag.tag_id.in_(selected_tag_ids))
            .add_columns(match_count.label("match_count"))
            .group_by(Document.id)
            .order_by(match_count.desc(), Document.updated_at.desc())
            .all()
        )
        ordered: list[Document] = []
        for doc, count in rows:
            doc.match_count = int(count)
            ordered.append(doc)
    else:
        ordered = base.order_by(Document.updated_at.desc()).all()

    per_page = DOCUMENTS_PER_PAGE
    total = len(ordered)
    pages = max(1, -(-total // per_page))
    page = min(max(1, request.args.get("page", 1, type=int) or 1), pages)
    start = (page - 1) * per_page
    documents = ordered[start:start + per_page]

    pagination_args = request.args.to_dict(flat=False)
    pagination_args.pop("page", None)

    def page_url(page_number: int) -> str:
        return url_for("documents.search", page=page_number, **pagination_args)

    return render_template(
        "documents/search.html",
        documents=documents,
        total=total,
        page=page,
        pages=pages,
        page_url=page_url,
        tags=Tag.query.filter_by(user_id=uid).order_by(Tag.name).all(),
        selected_tag_ids=selected_tag_ids,
        selected_tag_total=len(selected_tag_ids),
        categories=_ordered_categories(uid),
        sources=Source.query.filter_by(user_id=uid).order_by(Source.name).all(),
        authors=Author.query.filter_by(user_id=uid).order_by(Author.name).all(),
        q=q,
        author=author,
        source=source,
        active_category=category_id,
        active_type=doc_type,
        active_year=year,
        year_from=year_from,
        year_to=year_to,
        reading_status=reading_status or "",
        rating_min=rating_min or 0,
    )


@bp.route("/<int:doc_id>")
@login_required
def detail(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    return render_template("documents/detail.html", doc=doc)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("文献标题不能为空。", "danger")
            return redirect(url_for("documents.new"))

        doc = Document(user_id=current_user.id, title=title)
        db.session.add(doc)
        db.session.flush()
        try:
            _persist_document_form(doc, request.form, request.files.getlist("attachments"))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("保存失败：条码或副本号已被其他文献占用。", "danger")
            return redirect(url_for("documents.new"))
        except Exception as exc:
            db.session.rollback()
            flash(f"保存失败：{exc}", "danger")
            return redirect(url_for("documents.new"))

        record_activity(
            current_user.id,
            "document_create",
            "Create document",
            {"document_id": doc.id, "title": doc.title},
        )
        flash("文献已创建。", "success")
        return redirect(url_for("documents.detail", doc_id=doc.id))

    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    return render_template(
        "documents/edit.html",
        doc=None,
        categories=categories,
        authors_text="",
    )


@bp.route("/<int:doc_id>/edit", methods=["GET", "POST"])
@login_required
def edit(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("文献标题不能为空。", "danger")
            return redirect(url_for("documents.edit", doc_id=doc_id))
        try:
            _persist_document_form(doc, request.form, request.files.getlist("attachments"))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("保存失败：条码或副本号已被其他文献占用。", "danger")
            return redirect(url_for("documents.edit", doc_id=doc_id))
        except Exception as exc:
            db.session.rollback()
            flash(f"保存失败：{exc}", "danger")
            return redirect(url_for("documents.edit", doc_id=doc_id))

        record_activity(
            current_user.id,
            "document_edit",
            "Edit document",
            {"document_id": doc.id, "title": doc.title},
        )
        flash("文献已保存。", "success")
        return redirect(url_for("documents.detail", doc_id=doc.id))

    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    authors_text = upsert.authors_field_to_text(doc.author_links)
    return render_template(
        "documents/edit.html",
        doc=doc,
        categories=categories,
        authors_text=authors_text,
    )


@bp.route("/api/author_lookup")
@login_required
def author_lookup():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify(name="", authors=[], next_code=1)

    authors = upsert.peek_authors_by_name(name, current_user.id)
    counter = db.session.get(AuthorCode, (current_user.id, name))
    next_code = counter.next_code if counter else 1

    items = []
    for author in authors:
        row = (
            db.session.query(Document)
            .join(DocumentAuthor, DocumentAuthor.document_id == Document.id)
            .filter(
                DocumentAuthor.author_id == author.id,
                Document.user_id == current_user.id,
            )
            .order_by(Document.updated_at.desc())
            .first()
        )
        sample_doc = (
            {"id": row.id, "title": row.title, "year": row.publication_year}
            if row
            else None
        )
        items.append(
            {
                "id": author.id,
                "code": author.code,
                "affiliations": [aff.name for aff in author.affiliations],
                "sample_doc": sample_doc,
            }
        )

    return jsonify(name=name, authors=items, next_code=next_code)


@bp.route("/recognize_pdf", methods=["POST"])
@login_required
def recognize_pdf():
    uploaded = request.files.get("pdf")
    if not uploaded or not uploaded.filename:
        return jsonify(ok=False, error="缺少 PDF 文件。"), 400
    if not uploaded.filename.lower().endswith(".pdf"):
        return jsonify(ok=False, error="仅支持 PDF 文件。"), 400

    file_bytes = uploaded.read()
    if not file_bytes:
        return jsonify(ok=False, error="上传的 PDF 为空。"), 400

    try:
        parsed = mineru_client.parse_pdf(
            _get_mineru_url(current_user.id),
            file_bytes,
            uploaded.filename,
            backend="pipeline",
        )
    except mineru_client.MineruError as exc:
        return jsonify(ok=False, error=str(exc)), 502

    meta = pdf_metadata.extract_metadata(parsed)
    markdown = _build_combined_markdown(uploaded.filename, meta, parsed.get("md", ""))

    record_activity(
        current_user.id,
        "pdf_recognize",
        "Recognize PDF",
        {"filename": uploaded.filename},
    )
    return jsonify(
        ok=True,
        filename=uploaded.filename,
        suggested_fields={
            "title": meta.get("title", ""),
            "authors": meta.get("authors", []),
            "affiliations": meta.get("affiliations", []),
            "emails": meta.get("emails", []),
            "abstract": meta.get("abstract", ""),
            "keywords": meta.get("keywords", []),
            "doi": meta.get("doi", ""),
            "year": meta.get("year"),
            "source": meta.get("source", ""),
        },
        markdown=markdown,
    )


@bp.route("/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete(doc_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    cleaned = _delete_document_and_collect_cleanup(doc)
    db.session.commit()

    record_activity(
        current_user.id,
        "document_delete",
        "Delete document",
        {"document_id": doc_id},
    )

    flash(f"文献已删除{_cleanup_summary_text(cleaned)}。", "info")
    return redirect(url_for("documents.list_documents"))


@bp.route("/bulk-delete", methods=["POST"])
@login_required
def bulk_delete():
    documents, early_response = _selected_documents_or_redirect()
    if early_response is not None:
        return early_response

    cleanup_totals: dict[str, int] = {}
    deleted_ids: list[int] = []
    for doc in documents:
        cleaned = _delete_document_and_collect_cleanup(doc)
        deleted_ids.append(doc.id)
        for key, value in cleaned.items():
            cleanup_totals[key] = cleanup_totals.get(key, 0) + value

    db.session.commit()

    record_activity(
        current_user.id,
        "document_bulk_delete",
        "Bulk delete documents",
        {"count": len(deleted_ids), "document_ids": deleted_ids[:50]},
    )

    flash(
        f"已删除 {len(deleted_ids)} 篇文献{_cleanup_summary_text(cleanup_totals)}。",
        "info",
    )
    return redirect(
        url_for(
            "documents.list_documents",
            **_list_redirect_params_from_form(request.form),
        )
    )


@bp.route("/bulk-category", methods=["POST"])
@login_required
def bulk_category():
    documents, early_response = _selected_documents_or_redirect()
    if early_response is not None:
        return early_response

    category_token = (request.form.get("category_id") or "").strip()
    if not category_token:
        flash("请选择目标分类。", "warning")
        return redirect(
            url_for(
                "documents.list_documents",
                **_list_redirect_params_from_form(request.form),
            )
        )

    category = None
    if category_token != "__none__":
        try:
            category_id = int(category_token)
        except ValueError:
            flash("分类参数无效。", "danger")
            return redirect(
                url_for(
                    "documents.list_documents",
                    **_list_redirect_params_from_form(request.form),
                )
            )
        category = Category.query.filter_by(
            id=category_id,
            user_id=current_user.id,
        ).first()
        if category is None:
            flash("目标分类不存在。", "danger")
            return redirect(
                url_for(
                    "documents.list_documents",
                    **_list_redirect_params_from_form(request.form),
                )
            )

    changed_ids: list[int] = []
    for document in documents:
        if document.category_id == (category.id if category else None):
            continue
        document.category = category
        changed_ids.append(document.id)

    if not changed_ids:
        flash("所选文献已在目标分类中。", "info")
        return redirect(
            url_for(
                "documents.list_documents",
                **_list_redirect_params_from_form(request.form),
            )
        )

    db.session.commit()

    record_activity(
        current_user.id,
        "document_bulk_category",
        "Bulk update document category",
        {
            "count": len(changed_ids),
            "document_ids": changed_ids[:50],
            "category_id": category.id if category else None,
            "category_name": category.name if category else None,
        },
    )

    target_name = category.name if category else "未分类"
    flash(f"已将 {len(changed_ids)} 篇文献移动到“{target_name}”。", "success")
    return redirect(
        url_for(
            "documents.list_documents",
            **_list_redirect_params_from_form(request.form),
        )
    )


@bp.route("/<int:doc_id>/file/<int:file_id>")
@login_required
def download_file(doc_id, file_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    file_record = File.query.filter_by(id=file_id, document_id=doc.id).first_or_404()
    record_activity(
        current_user.id,
        "file_download",
        "Download attachment",
        {
            "document_id": doc.id,
            "file_id": file_id,
            "filename": file_record.original_name,
        },
    )
    upload_root = current_app.config["UPLOAD_FOLDER"]
    return send_from_directory(
        upload_root,
        file_record.file_path,
        download_name=file_record.original_name,
        as_attachment=request.args.get("download") == "1",
    )


@bp.route("/<int:doc_id>/file/<int:file_id>/delete", methods=["POST"])
@login_required
def delete_file(doc_id, file_id):
    doc = Document.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()
    file_record = File.query.filter_by(id=file_id, document_id=doc.id).first_or_404()
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    try:
        (upload_root / file_record.file_path).unlink(missing_ok=True)
    except Exception:
        pass
    db.session.delete(file_record)
    db.session.commit()
    record_activity(
        current_user.id,
        "file_delete",
        "Delete attachment",
        {
            "document_id": doc.id,
            "file_id": file_id,
            "filename": file_record.original_name,
        },
    )
    flash("附件已删除。", "info")
    return redirect(url_for("documents.detail", doc_id=doc_id))
