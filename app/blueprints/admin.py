from __future__ import annotations

from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import User
from ..services.ai_agent import record_activity

bp = Blueprint("admin", __name__, template_folder="../templates")


def _admin_guard(require_primary: bool = False):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.can_review_registrations_effective:
                abort(403)
            if require_primary and not current_user.is_admin:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _load_target_user_or_404(user_id: int) -> User:
    user = User.query.filter_by(id=user_id).first_or_404()
    if user.id == current_user.id:
        abort(400)
    return user


@bp.route("/")
@_admin_guard()
def index():
    pending_users = (
        User.query.filter_by(is_approved=False, approval_status="pending")
        .order_by(User.created_at.asc(), User.id.asc())
        .all()
    )
    all_users = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    return render_template(
        "admin/index.html",
        pending_users=pending_users,
        all_users=all_users,
        can_manage_roles=bool(current_user.is_admin),
    )


@bp.route("/users/<int:user_id>/approve", methods=["POST"])
@_admin_guard()
def approve_user(user_id: int):
    user = _load_target_user_or_404(user_id)
    user.is_approved = True
    user.approval_status = "approved"
    db.session.commit()
    record_activity(
        current_user.id,
        "admin_approve_user",
        "Approved user registration",
        {"target_user_id": user.id, "target_username": user.username},
    )
    flash(f"已通过账号 {user.username} 的注册申请。", "success")
    return redirect(url_for("admin.index"))


@bp.route("/users/<int:user_id>/reject", methods=["POST"])
@_admin_guard()
def reject_user(user_id: int):
    user = _load_target_user_or_404(user_id)
    user.is_approved = False
    user.approval_status = "rejected"
    db.session.commit()
    record_activity(
        current_user.id,
        "admin_reject_user",
        "Rejected user registration",
        {"target_user_id": user.id, "target_username": user.username},
    )
    flash(f"已拒绝账号 {user.username} 的注册申请。", "warning")
    return redirect(url_for("admin.index"))


@bp.route("/users/<int:user_id>/grant-reviewer", methods=["POST"])
@_admin_guard(require_primary=True)
def grant_reviewer(user_id: int):
    user = _load_target_user_or_404(user_id)
    user.can_review_registrations = True
    db.session.commit()
    record_activity(
        current_user.id,
        "admin_grant_reviewer",
        "Granted reviewer role",
        {"target_user_id": user.id, "target_username": user.username},
    )
    flash(f"已将 {user.username} 设为次级管理员。", "success")
    return redirect(url_for("admin.index"))


@bp.route("/users/<int:user_id>/revoke-reviewer", methods=["POST"])
@_admin_guard(require_primary=True)
def revoke_reviewer(user_id: int):
    user = _load_target_user_or_404(user_id)
    if user.is_admin:
        abort(400)
    user.can_review_registrations = False
    db.session.commit()
    record_activity(
        current_user.id,
        "admin_revoke_reviewer",
        "Revoked reviewer role",
        {"target_user_id": user.id, "target_username": user.username},
    )
    flash(f"已取消 {user.username} 的次级管理员权限。", "info")
    return redirect(url_for("admin.index"))
