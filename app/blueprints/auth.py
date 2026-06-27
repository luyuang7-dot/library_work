import os
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, limiter
from ..models import User
from ..services.ai_agent import record_activity

bp = Blueprint("auth", __name__)
_LOGIN_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5 per 15 minutes")


def _login_limit_key() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    ip_addr = forwarded_for.split(",")[0].strip() or request.remote_addr or "unknown"
    username = (request.form.get("username") or "").strip().lower() or "anonymous"
    return f"{ip_addr}:{username}"


def _login_limit_value() -> str:
    return str(current_app.config.get("LOGIN_RATE_LIMIT", _LOGIN_LIMIT))


def validate_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "密码长度至少需要 8 位。"
    classes = 0
    if any(char.islower() for char in password):
        classes += 1
    if any(char.isupper() for char in password):
        classes += 1
    if any(char.isdigit() for char in password):
        classes += 1
    if any(not char.isalnum() for char in password):
        classes += 1
    if classes < 2:
        return "密码至少需要包含字母、数字、符号中的两类。"
    return None


def _safe_next_url() -> str:
    next_url = (request.args.get("next") or "").strip()
    if not next_url:
        return url_for("documents.list_documents")
    parts = urlsplit(next_url)
    if parts.scheme or parts.netloc or not next_url.startswith("/"):
        return url_for("documents.list_documents")
    if next_url.startswith("//"):
        return url_for("documents.list_documents")
    return next_url


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("documents.list_documents"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if not username or not password:
            flash("用户名和密码不能为空。", "danger")
            return render_template("auth/register.html")
        if password != password2:
            flash("两次输入的密码不一致。", "danger")
            return render_template("auth/register.html")
        password_error = validate_password_strength(password)
        if password_error:
            flash(password_error, "danger")
            return render_template("auth/register.html")
        if User.query.filter_by(username=username).first():
            flash("用户名已存在。", "danger")
            return render_template("auth/register.html")
        if email and User.query.filter_by(email=email).first():
            flash("该邮箱已被注册。", "danger")
            return render_template("auth/register.html")

        user = User(
            username=username,
            email=email,
            is_admin=False,
            can_review_registrations=False,
            is_approved=False,
            approval_status="pending",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        record_activity(
            user.id,
            "auth_register",
            "User registered and is awaiting admin approval",
        )
        flash(
            "注册申请已提交，需等待管理员审核通过后才能登录。",
            "success",
        )
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_login_limit_value, key_func=_login_limit_key, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("documents.list_documents"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("用户名或密码错误。", "danger")
            return render_template("auth/login.html"), 401
        if user.approval_status_value == "rejected":
            flash("你的注册申请已被管理员拒绝。", "danger")
            return render_template("auth/login.html"), 403
        if not user.is_approved:
            flash("你的账号仍在等待管理员审核。", "warning")
            return render_template("auth/login.html"), 403
        login_user(user, remember=bool(request.form.get("remember")))
        record_activity(user.id, "auth_login", "User logged in")
        return redirect(_safe_next_url())
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    record_activity(current_user.id, "auth_logout", "User logged out")
    logout_user()
    flash("你已退出登录。", "info")
    return redirect(url_for("auth.login"))
