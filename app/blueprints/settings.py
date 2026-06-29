from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from config import BaseConfig

from .auth import validate_password_strength
from ..extensions import db
from ..models import UserSetting
from ..services import mineru_client
from ..services.ai_agent import (
    DEFAULT_AGENT_NAME,
    DEFAULT_DAILY_ROLLUP_MINUTE,
    InvalidAIAgentURLError,
    apply_agent_profile_updates,
    format_daily_rollup_time,
    format_fixed_prune_time,
    get_or_create_setting,
    record_activity,
    validate_ai_agent_api_url,
)

bp = Blueprint("settings", __name__)

DEFAULT_MINERU_URL = BaseConfig.DEFAULT_MINERU_URL


def _get_or_create_settings() -> UserSetting:
    settings = db.session.get(UserSetting, current_user.id)
    if settings is None:
        settings = UserSetting(user_id=current_user.id, mineru_url=DEFAULT_MINERU_URL)
        db.session.add(settings)
        db.session.commit()
    return settings


def _handle_password_change():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not current_password or not new_password or not confirm_password:
        flash("请完整填写所有密码字段。", "danger")
        return redirect(url_for("settings.index"))
    if not current_user.check_password(current_password):
        flash("当前密码不正确。", "danger")
        return redirect(url_for("settings.index"))
    if new_password != confirm_password:
        flash("两次输入的新密码不一致。", "danger")
        return redirect(url_for("settings.index"))
    if new_password == current_password:
        flash("新密码不能与当前密码相同。", "danger")
        return redirect(url_for("settings.index"))

    password_error = validate_password_strength(new_password)
    if password_error:
        flash(password_error, "danger")
        return redirect(url_for("settings.index"))

    current_user.set_password(new_password)
    db.session.commit()
    record_activity(current_user.id, "password_change", "User changed account password")
    flash("密码修改成功。", "success")
    return redirect(url_for("settings.index"))


@bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    settings = _get_or_create_settings()
    agent = get_or_create_setting(current_user.id)

    if request.method == "POST":
        action = (request.form.get("action") or request.form.get("form_name") or "").strip()

        if action == "change_password":
            return _handle_password_change()

        if action == "mineru":
            settings.mineru_url = (request.form.get("mineru_url") or "").strip() or DEFAULT_MINERU_URL
            db.session.commit()
            record_activity(current_user.id, "settings_save", "Saved MinerU settings")
            flash("MinerU 设置已保存。", "success")
            return redirect(url_for("settings.index"))

        if action != "save_ai_journal":
            flash("未识别的设置操作。", "danger")
            return redirect(url_for("settings.index"))

        agent.agent_name = (
            (request.form.get("agent_name") or "").strip()[:64] or DEFAULT_AGENT_NAME
        )
        agent.enabled = bool(request.form.get("agent_enabled"))

        api_url = (request.form.get("ai_api_url") or "").strip()
        if api_url:
            try:
                agent.api_url = validate_ai_agent_api_url(api_url)
            except InvalidAIAgentURLError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("settings.index"))
        else:
            agent.api_url = None

        agent.model = (request.form.get("ai_model") or "").strip()[:64] or None
        apply_agent_profile_updates(agent, request.form)
        agent.daily_rollup_minute = DEFAULT_DAILY_ROLLUP_MINUTE

        if request.form.get("clear_ai_api_key"):
            agent.api_key = None
        else:
            api_key = (request.form.get("ai_api_key") or "").strip()
            if api_key:
                agent.api_key = api_key

        db.session.commit()
        record_activity(current_user.id, "settings_save", "Saved AI journal settings")
        flash("AI 日志设置已保存。", "success")
        return redirect(url_for("settings.index"))

    return render_template(
        "settings/index.html",
        settings=settings,
        default_url=DEFAULT_MINERU_URL,
        agent=agent,
        daily_rollup_time=format_daily_rollup_time(DEFAULT_DAILY_ROLLUP_MINUTE),
        daily_prune_time=format_fixed_prune_time(),
    )


@bp.route("/test_mineru", methods=["POST"])
@login_required
def test_mineru():
    url = (request.form.get("mineru_url") or "").strip()
    if not url:
        return jsonify(ok=False, error="请输入 MinerU 地址。")
    try:
        info = mineru_client.health_check(url, timeout=4.0)
        return jsonify(
            ok=True,
            version=info.get("version"),
            status=info.get("status"),
            queued=info.get("queued_tasks"),
        )
    except mineru_client.MineruError as exc:
        return jsonify(ok=False, error=str(exc))
