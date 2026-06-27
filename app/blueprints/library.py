from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Affiliation, Author, Keyword, Publisher, Source, Tag
from ..services import dict_cleanup
from ..services.ai_agent import record_activity

bp = Blueprint("library", __name__)


@bp.route("/")
@login_required
def index():
    uid = current_user.id
    authors = Author.query.filter_by(user_id=uid).order_by(Author.name).all()
    affiliations = Affiliation.query.filter_by(user_id=uid).order_by(Affiliation.name).all()
    publishers = Publisher.query.filter_by(user_id=uid).order_by(Publisher.name).all()
    sources = Source.query.filter_by(user_id=uid).order_by(Source.name).all()
    keywords = Keyword.query.filter_by(user_id=uid).order_by(Keyword.name).all()
    tags = Tag.query.filter_by(user_id=uid).order_by(Tag.name).all()
    merge_audits = dict_cleanup.list_merge_audits(uid, limit=20)
    return render_template(
        "library/index.html",
        authors=authors,
        affiliations=affiliations,
        publishers=publishers,
        sources=sources,
        keywords=keywords,
        tags=tags,
        merge_audits=merge_audits,
    )


@bp.route("/authors/<int:author_id>/delete", methods=["POST"])
@login_required
def delete_author(author_id):
    a = Author.query.filter_by(id=author_id, user_id=current_user.id).first()
    if a and not a.document_links:
        db.session.delete(a)
        db.session.commit()
        record_activity(current_user.id, "dict_delete", "删除作者", {"author_id": author_id})
        flash("作者已删除", "info")
    else:
        flash("作者不存在或关联了文献，无法删除", "warning")
    return redirect(url_for("library.index"))


@bp.route("/affiliations/<int:aff_id>/delete", methods=["POST"])
@login_required
def delete_affiliation(aff_id):
    a = Affiliation.query.filter_by(id=aff_id, user_id=current_user.id).first()
    if a and not a.authors:
        db.session.delete(a)
        db.session.commit()
        record_activity(current_user.id, "dict_delete", "删除单位", {"affiliation_id": aff_id})
        flash("单位已删除", "info")
    else:
        flash("单位不存在或关联了作者，无法删除", "warning")
    return redirect(url_for("library.index"))


@bp.route("/publishers/<int:pub_id>/delete", methods=["POST"])
@login_required
def delete_publisher(pub_id):
    p = Publisher.query.filter_by(id=pub_id, user_id=current_user.id).first()
    if p and not p.sources:
        db.session.delete(p)
        db.session.commit()
        record_activity(current_user.id, "dict_delete", "删除出版社", {"publisher_id": pub_id})
        flash("出版社已删除", "info")
    else:
        flash("出版社不存在或关联了来源，无法删除", "warning")
    return redirect(url_for("library.index"))


@bp.route("/sources/<int:src_id>/delete", methods=["POST"])
@login_required
def delete_source(src_id):
    s = Source.query.filter_by(id=src_id, user_id=current_user.id).first()
    if s and not s.documents:
        db.session.delete(s)
        db.session.commit()
        record_activity(current_user.id, "dict_delete", "删除来源", {"source_id": src_id})
        flash("来源已删除", "info")
    else:
        flash("来源不存在或关联了文献，无法删除", "warning")
    return redirect(url_for("library.index"))


@bp.route("/keywords/<int:kw_id>/delete", methods=["POST"])
@login_required
def delete_keyword(kw_id):
    k = Keyword.query.filter_by(id=kw_id, user_id=current_user.id).first()
    if k and not k.documents:
        db.session.delete(k)
        db.session.commit()
        flash("关键词已删除", "info")
    else:
        flash("关键词不存在或关联了文献，无法删除", "warning")
    return redirect(url_for("library.index"))


@bp.route("/tags/<int:tag_id>/delete", methods=["POST"])
@login_required
def delete_tag(tag_id):
    t = Tag.query.filter_by(id=tag_id, user_id=current_user.id).first()
    if t and not t.documents:
        db.session.delete(t)
        db.session.commit()
        flash("标签已删除", "info")
    else:
        flash("标签不存在或关联了文献，无法删除", "warning")
    return redirect(url_for("library.index"))


# ---- Cleanup (orphan + duplicate detection) ----


@bp.route("/cleanup_scan")
@login_required
def cleanup_scan():
    uid = current_user.id
    orphans = dict_cleanup.scan_orphans(uid)
    duplicates = dict_cleanup.find_potential_duplicates(uid)
    return jsonify(
        orphans={k: [item.name for item in v] for k, v in orphans.items()},
        duplicates={k: [[item.name for item in group] for group in groups] for k, groups in duplicates.items()},
    )


@bp.route("/cleanup_apply", methods=["POST"])
@login_required
def cleanup_apply():
    try:
        counts = dict_cleanup.delete_all_orphans(current_user.id)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e))
    record_activity(current_user.id, "cleanup_apply", "清理孤立字典项", counts)
    return jsonify(ok=True, deleted=counts)


@bp.route("/merge_preview")
@login_required
def merge_preview():
    data = dict_cleanup.merge_preview(current_user.id)
    return jsonify(ok=True, **data)


@bp.route("/merge_apply", methods=["POST"])
@login_required
def merge_apply():
    try:
        result = dict_cleanup.merge_apply(current_user.id)
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e))
    if result.get("ok"):
        record_activity(current_user.id, "merge_apply", "合并字典项", result)
    return jsonify(result)


@bp.route("/merge_rollback", methods=["POST"])
@login_required
def merge_rollback():
    payload = request.get_json(silent=True) or {}
    audit_id = payload.get("audit_id")
    try:
        if audit_id is None:
            result = dict_cleanup.merge_rollback_last(current_user.id)
        else:
            result = dict_cleanup.merge_rollback_by_audit_id(current_user.id, int(audit_id))
    except Exception as e:
        db.session.rollback()
        return jsonify(ok=False, error=str(e))
    if result.get("ok"):
        record_activity(current_user.id, "merge_rollback", "回滚字典合并", result)
    return jsonify(result)


@bp.route("/merge_audits")
@login_required
def merge_audits():
    return jsonify(ok=True, items=dict_cleanup.list_merge_audits(current_user.id, limit=50))


# ---- JSON autocomplete endpoints ----


@bp.route("/api/sources")
@login_required
def api_sources():
    uid = current_user.id
    return jsonify([s.name for s in Source.query.filter_by(user_id=uid).order_by(Source.name).all()])


@bp.route("/api/publishers")
@login_required
def api_publishers():
    uid = current_user.id
    return jsonify([p.name for p in Publisher.query.filter_by(user_id=uid).order_by(Publisher.name).all()])


@bp.route("/api/authors")
@login_required
def api_authors():
    uid = current_user.id
    return jsonify([a.name for a in Author.query.filter_by(user_id=uid).order_by(Author.name).all()])


@bp.route("/api/affiliations")
@login_required
def api_affiliations():
    uid = current_user.id
    return jsonify([a.name for a in Affiliation.query.filter_by(user_id=uid).order_by(Affiliation.name).all()])
