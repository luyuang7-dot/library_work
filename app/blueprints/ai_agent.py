from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..extensions import db
from ..services.ai_agent import (
    DEFAULT_AGENT_NAME,
    apply_agent_profile_updates,
    get_or_create_setting,
    record_activity,
    serialize_assistant_state,
    summarize_and_prune_user_activities,
)

bp = Blueprint("ai_agent", __name__)


@bp.route("/api/state", methods=["GET", "POST"])
@login_required
def api_state():
    setting = get_or_create_setting(current_user.id)
    if request.method == "GET":
        return jsonify(ok=True, state=serialize_assistant_state(setting))

    payload = request.get_json(silent=True) or {}
    if "agent_name" in payload:
        name = (payload.get("agent_name") or "").strip()
        setting.agent_name = name[:64] or setting.agent_name or DEFAULT_AGENT_NAME
    if "enabled" in payload:
        setting.enabled = bool(payload.get("enabled"))
    apply_agent_profile_updates(setting, payload)
    db.session.commit()
    return jsonify(ok=True, state=serialize_assistant_state(setting))


@bp.route("/api/activity", methods=["POST"])
@login_required
def api_activity():
    payload = request.get_json(silent=True) or {}
    record_activity(
        current_user.id,
        payload.get("event_type") or "assistant_interaction",
        payload.get("label") or "Assistant interaction",
        payload.get("metadata") or {},
        silent=False,
    )
    return jsonify(ok=True)


@bp.route("/api/rollup/run", methods=["POST"])
@login_required
def rollup_run():
    result = summarize_and_prune_user_activities(current_user.id)
    return jsonify(result)
