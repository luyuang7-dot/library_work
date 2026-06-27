from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from ..extensions import db
from ..services.ai_agent import (
    DEFAULT_AGENT_NAME,
    apply_agent_profile_updates,
    get_or_create_setting,
    record_activity,
    serialize_setting,
    summarize_and_prune_user_activities,
)

bp = Blueprint("ai_agent", __name__)


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


@bp.route("/api/state", methods=["GET", "POST"])
@login_required
def api_state():
    setting = get_or_create_setting(current_user.id)
    if request.method == "GET":
        return jsonify(ok=True, state=serialize_setting(setting))

    payload = request.get_json(silent=True) or {}
    if "agent_name" in payload:
        name = (payload.get("agent_name") or "").strip()
        setting.agent_name = name[:64] or setting.agent_name or DEFAULT_AGENT_NAME
    if "enabled" in payload:
        setting.enabled = bool(payload.get("enabled"))
    if "facing" in payload:
        setting.facing = "left" if payload.get("facing") == "left" else "right"
    if "position_x" in payload:
        setting.position_x = _clamp_int(
            payload.get("position_x"), 0, 10000, setting.position_x or 24
        )
    if "position_y" in payload:
        setting.position_y = _clamp_int(
            payload.get("position_y"), 0, 10000, setting.position_y or 24
        )
    apply_agent_profile_updates(setting, payload)
    db.session.commit()
    record_activity(
        current_user.id,
        "agent_state_update",
        "Updated AI Agent state",
        {
            "fields": sorted(payload.keys()),
        },
    )
    return jsonify(ok=True, state=serialize_setting(setting))


@bp.route("/api/activity", methods=["POST"])
@login_required
def api_activity():
    payload = request.get_json(silent=True) or {}
    record_activity(
        current_user.id,
        payload.get("event_type") or "activity",
        payload.get("label") or "User activity",
        payload.get("metadata") or {},
        silent=False,
    )
    return jsonify(ok=True)


@bp.route("/api/rollup/run", methods=["POST"])
@login_required
def rollup_run():
    result = summarize_and_prune_user_activities(current_user.id)
    return jsonify(result)
