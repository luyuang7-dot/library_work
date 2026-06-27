from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Category, Document

bp = Blueprint("categories", __name__)


@bp.route("/")
@login_required
def list_categories():
    cats = (
        Category.query.filter_by(user_id=current_user.id)
        .order_by(Category.name)
        .all()
    )
    # build tree
    by_id = {c.id: {"node": c, "children": []} for c in cats}
    roots = []
    for c in cats:
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id]["children"].append(by_id[c.id])
        else:
            roots.append(by_id[c.id])
    return render_template("categories/tree.html", roots=roots, all_categories=cats)


@bp.route("/", methods=["POST"])
@login_required
def create():
    name = (request.form.get("name") or "").strip()
    parent_id = request.form.get("parent_id", type=int)
    if not name:
        flash("分类名不能为空", "danger")
        return redirect(url_for("categories.list_categories"))
    if parent_id:
        parent = Category.query.filter_by(id=parent_id, user_id=current_user.id).first()
        if not parent:
            flash("父分类无效", "danger")
            return redirect(url_for("categories.list_categories"))
    cat = Category(user_id=current_user.id, name=name, parent_id=parent_id)
    db.session.add(cat)
    db.session.commit()
    flash("已创建", "success")
    return redirect(url_for("categories.list_categories"))


@bp.route("/<int:cat_id>/rename", methods=["POST"])
@login_required
def rename(cat_id):
    cat = Category.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("名称不能为空", "danger")
    else:
        cat.name = name
        db.session.commit()
        flash("已重命名", "success")
    return redirect(url_for("categories.list_categories"))


@bp.route("/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete(cat_id):
    cat = Category.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()
    # move children up to root, and detach documents
    for child in cat.children:
        child.parent_id = cat.parent_id
    Document.query.filter_by(category_id=cat.id).update({"category_id": None})
    db.session.delete(cat)
    db.session.commit()
    flash("分类已删除（其下文献已变为未分类）", "info")
    return redirect(url_for("categories.list_categories"))
