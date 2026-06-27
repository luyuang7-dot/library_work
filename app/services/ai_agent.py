from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from flask import current_app, has_app_context

from ..extensions import db
from ..models import AIAgentActivity, AIAgentJournal, AIAgentSetting

DEFAULT_AGENT_NAME = "小吱"
DEFAULT_POSITION_X = 24
DEFAULT_POSITION_Y = 24
DEFAULT_DAILY_ROLLUP_MINUTE = 23 * 60 + 59
DEFAULT_DAILY_PRUNE_MINUTE = 12 * 60
DEFAULT_DAILY_PRUNE_WINDOW_MINUTES = 60
WEEKLY_ROLLUP_DAYS = 7
ACTIVITY_FETCH_LIMIT = 500

DEFAULT_TONE = "gentle"
DEFAULT_ROLE = "companion"
DEFAULT_PERSONALITY = "thoughtful"

AI_AGENT_TONE_OPTIONS = {
    "gentle": "温柔陪伴型：语气柔和、耐心，让人放松",
    "professional": "专业干练型：表达清晰、克制，重点明确",
    "lively": "轻快活力型：语气明快、积极，有互动感",
}

AI_AGENT_ROLE_OPTIONS = {
    "companion": "桌面伙伴：像一直陪着你的贴身小助手",
    "secretary": "秘书助理：像细致可靠、会帮你理顺事项的助理",
    "research_assistant": "研究助理：像擅长归纳总结、关注进度的学术助手",
}

AI_AGENT_PERSONALITY_OPTIONS = {
    "thoughtful": "细腻体贴：善于总结重点，也会照顾你的节奏",
    "decisive": "果断利落：更偏行动导向，结论和建议更直接",
    "playful": "轻松俏皮：表达更亲切活泼，但不脱离事实",
}

AI_AGENT_PROFILE_FIELDS = {
    "tone": (AI_AGENT_TONE_OPTIONS, DEFAULT_TONE),
    "role": (AI_AGENT_ROLE_OPTIONS, DEFAULT_ROLE),
    "personality": (AI_AGENT_PERSONALITY_OPTIONS, DEFAULT_PERSONALITY),
}


class AIAgentError(Exception):
    """Raised when the configured AI agent service cannot generate a journal."""


class InvalidAIAgentURLError(ValueError):
    """Raised when the configured AI agent URL is unsafe or malformed."""


@dataclass(frozen=True)
class RollupPlan:
    window_start: datetime
    window_end: datetime
    slot_label: str


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _as_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone()
    return dt.astimezone()


def _to_utc(dt: datetime) -> datetime:
    local = _as_local(dt)
    if local is None:
        raise ValueError("datetime is required")
    return local.astimezone(timezone.utc)


def _local_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _local_period_start(period: str) -> datetime:
    now = _now_local()
    if period == "today":
        return _to_utc(_local_day_start(now))
    if period == "week":
        end_date = now.date()
        start_date = end_date - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
        return _to_utc(datetime.combine(start_date, datetime.min.time(), now.tzinfo))
    raise ValueError("period must be 'today' or 'week'")


def journal_date_range(period: str) -> tuple[date, date]:
    now = _now_local()
    local_today = now.date()
    if period == "today":
        return local_today, local_today
    if period == "week":
        start_date = local_today - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
        return start_date, local_today
    raise ValueError("period must be 'today' or 'week'")


def _clamp_daily_rollup_minute(value: int | None) -> int:
    try:
        minute = int(value) if value is not None else DEFAULT_DAILY_ROLLUP_MINUTE
    except (TypeError, ValueError):
        return DEFAULT_DAILY_ROLLUP_MINUTE
    return min(max(minute, 0), 23 * 60 + 59)


def format_daily_rollup_time(value: int | None) -> str:
    minute = _clamp_daily_rollup_minute(value)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def format_fixed_prune_time() -> str:
    return f"{DEFAULT_DAILY_PRUNE_MINUTE // 60:02d}:{DEFAULT_DAILY_PRUNE_MINUTE % 60:02d}"


def _normalize_choice(value: str | None, options: dict[str, str], default: str) -> str:
    raw = (value or "").strip()
    return raw if raw in options else default


def normalize_profile_choice(field: str, value: str | None) -> str:
    options, default = AI_AGENT_PROFILE_FIELDS[field]
    return _normalize_choice(value, options, default)


def _normalize_user_preference(value: str | None) -> str:
    return (value or "").strip()[:500]


def _normalize_setting_profile(setting: AIAgentSetting) -> bool:
    changed = False
    for field in AI_AGENT_PROFILE_FIELDS:
        normalized = normalize_profile_choice(field, getattr(setting, field, None))
        if getattr(setting, field, None) != normalized:
            setattr(setting, field, normalized)
            changed = True

    normalized_preference = _normalize_user_preference(
        getattr(setting, "user_preference", "")
    )
    if getattr(setting, "user_preference", "") != normalized_preference:
        setting.user_preference = normalized_preference
        changed = True
    return changed


def apply_agent_profile_updates(setting: AIAgentSetting, source) -> None:
    for field in AI_AGENT_PROFILE_FIELDS:
        if field in source:
            setattr(setting, field, normalize_profile_choice(field, source.get(field)))
    if "user_preference" in source:
        setting.user_preference = _normalize_user_preference(source.get("user_preference"))


def _serialize_setting_profile(setting: AIAgentSetting) -> dict:
    return {
        "tone": normalize_profile_choice("tone", getattr(setting, "tone", None)),
        "role": normalize_profile_choice("role", getattr(setting, "role", None)),
        "personality": normalize_profile_choice(
            "personality",
            getattr(setting, "personality", None),
        ),
        "user_preference": _normalize_user_preference(
            getattr(setting, "user_preference", "")
        ),
    }


def get_or_create_setting(user_id: int, commit: bool = True) -> AIAgentSetting:
    setting = db.session.get(AIAgentSetting, user_id)
    needs_save = False
    if setting is None:
        setting = AIAgentSetting(
            user_id=user_id,
            agent_name=DEFAULT_AGENT_NAME,
            enabled=True,
            facing="right",
            position_x=DEFAULT_POSITION_X,
            position_y=DEFAULT_POSITION_Y,
            tone=DEFAULT_TONE,
            role=DEFAULT_ROLE,
            personality=DEFAULT_PERSONALITY,
            user_preference="",
            daily_rollup_minute=DEFAULT_DAILY_ROLLUP_MINUTE,
        )
        db.session.add(setting)
        needs_save = True
    elif setting.migrate_api_key_to_encrypted():
        needs_save = True
    if setting.daily_rollup_minute != DEFAULT_DAILY_ROLLUP_MINUTE:
        setting.daily_rollup_minute = DEFAULT_DAILY_ROLLUP_MINUTE
        needs_save = True
    if _normalize_setting_profile(setting):
        needs_save = True
    if needs_save:
        if commit:
            db.session.commit()
        else:
            db.session.flush()
    return setting


def serialize_setting(setting: AIAgentSetting) -> dict:
    profile = _serialize_setting_profile(setting)
    return {
        "agent_name": setting.agent_name or DEFAULT_AGENT_NAME,
        "enabled": bool(setting.enabled),
        "facing": setting.facing if setting.facing in {"left", "right"} else "right",
        "position_x": int(setting.position_x or DEFAULT_POSITION_X),
        "position_y": int(setting.position_y or DEFAULT_POSITION_Y),
        "api_url": setting.api_url or "",
        "api_key_configured": bool(setting.api_key),
        "model": setting.model or "",
        **profile,
        "daily_rollup_time": format_daily_rollup_time(DEFAULT_DAILY_ROLLUP_MINUTE),
        "daily_prune_time": format_fixed_prune_time(),
        "last_rollup_at": _as_local(setting.last_rollup_at).isoformat() if setting.last_rollup_at else None,
    }


def sanitize_metadata(metadata) -> dict:
    if not isinstance(metadata, dict):
        return {}
    safe = {}
    for key, value in metadata.items():
        if key in {"password", "api_key", "token", "secret"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)[:64]] = value
        else:
            safe[str(key)[:64]] = str(value)[:500]
    return safe


def record_activity(
    user_id: int,
    event_type: str,
    label: str,
    metadata: dict | None = None,
    *,
    commit: bool = True,
    silent: bool = True,
) -> AIAgentActivity | None:
    event_type = (event_type or "activity").strip()[:64] or "activity"
    label = (label or event_type).strip()[:256] or event_type
    metadata_json = json.dumps(
        sanitize_metadata(metadata), ensure_ascii=False, default=str
    )[:5000]
    activity = AIAgentActivity(
        user_id=user_id,
        event_type=event_type,
        label=label,
        metadata_json=metadata_json,
    )
    try:
        db.session.add(activity)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return activity
    except Exception:
        db.session.rollback()
        if silent:
            return None
        raise


def activities_for_period(user_id: int, period: str) -> list[AIAgentActivity]:
    if period not in {"today", "week"}:
        raise ValueError("period must be 'today' or 'week'")
    start = _local_period_start(period)
    return (
        AIAgentActivity.query.filter(
            AIAgentActivity.user_id == user_id,
            AIAgentActivity.created_at >= start,
        )
        .order_by(AIAgentActivity.created_at.asc())
        .limit(ACTIVITY_FETCH_LIMIT)
        .all()
    )


def activities_in_window(user_id: int, start: datetime, end: datetime) -> list[AIAgentActivity]:
    return (
        AIAgentActivity.query.filter(
            AIAgentActivity.user_id == user_id,
            AIAgentActivity.created_at >= start,
            AIAgentActivity.created_at < end,
        )
        .order_by(AIAgentActivity.created_at.asc())
        .limit(ACTIVITY_FETCH_LIMIT)
        .all()
    )


def _journal_title(period: str, start_date: date, end_date: date) -> str:
    if period == "daily":
        return f"{start_date.isoformat()} 日志"
    return f"{start_date.isoformat()} ~ {end_date.isoformat()} 周记"


def save_generated_journal(
    user_id: int,
    period: str,
    content: str,
    *,
    commit: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> AIAgentJournal:
    if period not in {"daily", "weekly"}:
        raise ValueError("period must be 'daily' or 'weekly'")
    if start_date is None or end_date is None:
        resolved_start, resolved_end = journal_date_range("today" if period == "daily" else "week")
        start_date = start_date or resolved_start
        end_date = end_date or resolved_end
    title = _journal_title(period, start_date, end_date)
    journal = (
        AIAgentJournal.query.filter_by(
            user_id=user_id,
            period=period,
            start_date=start_date,
        ).first()
    )
    if journal is None:
        journal = AIAgentJournal(
            user_id=user_id,
            period=period,
            start_date=start_date,
            end_date=end_date,
            title=title,
            content=content,
        )
        db.session.add(journal)
    else:
        journal.end_date = end_date
        journal.title = title
        journal.content = content
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return journal


def list_month_daily_journals(user_id: int, year: int, month: int) -> list[AIAgentJournal]:
    month_start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (
        AIAgentJournal.query.filter(
            AIAgentJournal.user_id == user_id,
            AIAgentJournal.period == "daily",
            AIAgentJournal.start_date >= month_start,
            AIAgentJournal.start_date < next_month,
        )
        .order_by(AIAgentJournal.start_date.asc())
        .all()
    )


def list_month_weekly_journals(user_id: int, range_start: date, range_end: date) -> list[AIAgentJournal]:
    return (
        AIAgentJournal.query.filter(
            AIAgentJournal.user_id == user_id,
            AIAgentJournal.period == "weekly",
            AIAgentJournal.start_date <= range_end,
            AIAgentJournal.end_date >= range_start,
        )
        .order_by(AIAgentJournal.start_date.asc())
        .all()
    )


def activity_to_dict(activity: AIAgentActivity) -> dict:
    try:
        metadata = json.loads(activity.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    created_at = _as_local(activity.created_at)
    return {
        "time": created_at.isoformat() if created_at else "",
        "event_type": activity.event_type,
        "label": activity.label,
        "metadata": metadata,
    }


def build_activity_summary(activities: list[AIAgentActivity]) -> str:
    if not activities:
        return "暂无记录到的使用活动。"
    lines = []
    for activity in activities:
        created_at = _as_local(activity.created_at)
        time_label = created_at.strftime("%Y-%m-%d %H:%M") if created_at else ""
        lines.append(f"- {time_label} [{activity.event_type}] {activity.label}")
    return "\n".join(lines)


def _build_journal_digest(journals: list[AIAgentJournal]) -> str:
    if not journals:
        return "暂无可用的历史日志。"
    blocks = []
    for journal in journals:
        blocks.append(
            f"## {journal.title}\n"
            f"{journal.content.strip()}"
        )
    return "\n\n".join(blocks)


def _extract_content(response_payload) -> str:
    if isinstance(response_payload, str):
        return response_payload.strip()
    if not isinstance(response_payload, dict):
        return json.dumps(response_payload, ensure_ascii=False)

    for key in ("content", "text", "result", "message"):
        value = response_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("content") or value.get("text")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()

    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(first.get("text"), str):
                return first["text"].strip()

    return json.dumps(response_payload, ensure_ascii=False)


def _is_disallowed_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    ) or ip in {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
    }


def validate_ai_agent_api_url(raw_url: str | None) -> str:
    api_url = (raw_url or "").strip()
    if not api_url:
        raise InvalidAIAgentURLError("Please provide an AI Agent API URL.")

    parsed = urlparse(api_url)
    if parsed.scheme.lower() != "https":
        raise InvalidAIAgentURLError("AI Agent API URL must use https://.")
    if not parsed.hostname:
        raise InvalidAIAgentURLError("AI Agent API URL must include a valid host.")
    if parsed.username or parsed.password:
        raise InvalidAIAgentURLError(
            "AI Agent API URL must not include embedded credentials."
        )

    hostname = parsed.hostname.strip().lower()
    if hostname == "localhost":
        raise InvalidAIAgentURLError("Localhost is not allowed for AI Agent API URL.")

    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None

    if direct_ip is not None:
        if _is_disallowed_ip(direct_ip):
            raise InvalidAIAgentURLError(
                "AI Agent API URL cannot point to a private or reserved IP address."
            )
    else:
        try:
            addrinfo = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            if has_app_context() and current_app.config.get("TESTING") and hostname.endswith(
                (".test", ".example", ".invalid")
            ):
                return parsed.geturl()
            raise InvalidAIAgentURLError(
                "AI Agent API URL host could not be resolved."
            ) from exc

        resolved_ips = set()
        for entry in addrinfo:
            sockaddr = entry[4]
            if not sockaddr:
                continue
            resolved_ips.add(sockaddr[0])
        if not resolved_ips:
            raise InvalidAIAgentURLError(
                "AI Agent API URL host did not resolve to any address."
            )
        for resolved_ip in resolved_ips:
            parsed_ip = ipaddress.ip_address(resolved_ip)
            if _is_disallowed_ip(parsed_ip):
                raise InvalidAIAgentURLError(
                    "AI Agent API URL resolved to a private or reserved IP address."
                )

    return parsed.geturl()


def _build_messages(
    setting: AIAgentSetting,
    period: str,
    activities: list[AIAgentActivity],
    *,
    previous_daily_content: str | None = None,
    source_journals: list[AIAgentJournal] | None = None,
    window_label: str | None = None,
) -> list[dict]:
    agent_name = setting.agent_name or DEFAULT_AGENT_NAME
    profile = _serialize_setting_profile(setting)
    tone = profile["tone"]
    role = profile["role"]
    personality = profile["personality"]
    user_preference = profile["user_preference"]
    preference_block = (
        f"用户额外偏好：{user_preference}。请在不偏离事实的前提下尽量满足。\n"
        if user_preference
        else ""
    )
    system_prompt = (
        f"你是用户在 Personal Library 文献管理系统里的桌面伙伴，名字叫{agent_name}。"
        f"你的身份设定是：{AI_AGENT_ROLE_OPTIONS[role]}。"
        f"你的语气要求是：{AI_AGENT_TONE_OPTIONS[tone]}。"
        f"你的性格要求是：{AI_AGENT_PERSONALITY_OPTIONS[personality]}。"
        f"{preference_block}"
        "请用第一人称写中文日志，要求简洁、有条理、基于事实、使用 Markdown，并在结尾给一句简短鼓励。"
    )

    if period == "week":
        history_text = _build_journal_digest(source_journals or [])
        user_prompt = (
            "\u4e0b\u9762\u662f\u7528\u6237\u6700\u8fd1\u4e03\u5929\u5df2\u7ecf\u751f\u6210\u7684\u65e5\u5fd7\uff0c\u8bf7\u57fa\u4e8e\u8fd9\u4e9b\u65e5\u5fd7\u5199\u4e00\u7bc7\u5468\u8bb0\u3002"
            "\u8981\u6c42\u91cd\u70b9\u6982\u62ec\u9636\u6bb5\u6027\u5de5\u4f5c\u3001\u5e38\u89c1\u64cd\u4f5c\u65b9\u5411\u548c\u6574\u4f53\u8fdb\u5c55\u3002\n\n"
            f"{history_text}"
        )
    else:
        activity_text = build_activity_summary(activities)
        previous_block = ""
        if previous_daily_content:
            previous_block = (
                "\u4e0b\u9762\u662f\u4eca\u5929\u6b64\u524d\u5df2\u7ecf\u751f\u6210\u7684\u65e5\u5fd7\uff0c\u8bf7\u5728\u4fdd\u7559\u5df2\u6709\u91cd\u70b9\u7684\u57fa\u7840\u4e0a\uff0c"
                "\u628a\u65b0\u65f6\u95f4\u6bb5\u5185\u7684\u64cd\u4f5c\u81ea\u7136\u5408\u5e76\u8fdb\u53bb\uff0c\u4e0d\u8981\u7b80\u5355\u91cd\u590d\u3002\n\n"
                f"{previous_daily_content.strip()}\n\n"
            )
        slot_block = (
            f"\u672c\u6b21\u65b0\u589e\u6d3b\u52a8\u65f6\u95f4\u6bb5\uff1a{window_label}\n\n"
            if window_label
            else ""
        )
        user_prompt = (
            "\u4e0b\u9762\u662f\u7528\u6237\u4eca\u5929\u5728 Personal Library \u7684\u4f7f\u7528\u8bb0\u5f55\uff0c\u8bf7\u751f\u6210\u4e00\u7bc7\u65e5\u5fd7\u3002\n\n"
            f"{previous_block}{slot_block}"
            "\u8fd9\u662f\u672c\u6b21\u65b0\u589e\u6d3b\u52a8\uff1a\n\n"
            f"{activity_text}"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _request_journal(
    setting: AIAgentSetting,
    messages: list[dict],
    *,
    timeout: float = 30.0,
) -> str:
    api_url = (setting.api_url or "").strip()
    if not api_url:
        raise AIAgentError("\u8bf7\u5148\u5728\u8bbe\u7f6e\u9875\u586b\u5199 AI Agent \u63a5\u5165 URL")
    try:
        api_url = validate_ai_agent_api_url(api_url)
    except InvalidAIAgentURLError as exc:
        raise AIAgentError(str(exc)) from exc

    model = (setting.model or "").strip()
    if not model:
        raise AIAgentError(
            "\u8bf7\u5148\u5728\u8bbe\u7f6e\u9875\u586b\u5199 AI \u6a21\u578b\u540d\u79f0\uff0c\u4f8b\u5982 deepseek-chat"
        )

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    api_key = (setting.api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        if response.is_redirect:
            redirect_target = response.headers.get("Location")
            try:
                validate_ai_agent_api_url(redirect_target)
            except InvalidAIAgentURLError as exc:
                raise AIAgentError(
                    f"AI Agent redirect target is not allowed: {exc}"
                ) from exc
            raise AIAgentError("AI Agent endpoint redirected the request unexpectedly.")
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AIAgentError(f"AI Agent \u8bf7\u6c42\u5931\u8d25: {exc}") from exc

    try:
        body = response.json()
    except ValueError:
        body = response.text

    content = _extract_content(body)
    if not content:
        raise AIAgentError("AI Agent \u8fd4\u56de\u4e3a\u7a7a")
    return content


def generate_journal(
    setting: AIAgentSetting,
    period: str,
    activities: list[AIAgentActivity],
    *,
    timeout: float = 30.0,
    previous_daily_content: str | None = None,
    source_journals: list[AIAgentJournal] | None = None,
    window_label: str | None = None,
) -> str:
    messages = _build_messages(
        setting,
        period,
        activities,
        previous_daily_content=previous_daily_content,
        source_journals=source_journals,
        window_label=window_label,
    )
    return _request_journal(setting, messages, timeout=timeout)


def _current_daily_journal(user_id: int, for_date: date) -> AIAgentJournal | None:
    return (
        AIAgentJournal.query.filter_by(
            user_id=user_id,
            period="daily",
            start_date=for_date,
        ).first()
    )


def _recent_daily_journals(user_id: int, end_date: date) -> list[AIAgentJournal]:
    start_date = end_date - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
    return (
        AIAgentJournal.query.filter(
            AIAgentJournal.user_id == user_id,
            AIAgentJournal.period == "daily",
            AIAgentJournal.start_date >= start_date,
            AIAgentJournal.start_date <= end_date,
        )
        .order_by(AIAgentJournal.start_date.asc())
        .all()
    )


def _archived_recent_daily_journals(user_id: int, end_date: date) -> list[AIAgentJournal]:
    start_date = end_date - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
    return (
        AIAgentJournal.query.filter(
            AIAgentJournal.user_id == user_id,
            AIAgentJournal.period == "daily",
            AIAgentJournal.archived_at.isnot(None),
            AIAgentJournal.start_date >= start_date,
            AIAgentJournal.start_date <= end_date,
        )
        .order_by(AIAgentJournal.start_date.asc())
        .all()
    )


def _latest_archived_daily_journal(user_id: int, on_date: date) -> AIAgentJournal | None:
    return (
        AIAgentJournal.query.filter_by(
            user_id=user_id,
            period="daily",
            start_date=on_date,
        )
        .filter(AIAgentJournal.archived_at.isnot(None))
        .order_by(AIAgentJournal.updated_at.desc())
        .first()
    )


def archive_daily_journal(journal: AIAgentJournal, *, archived_at: datetime | None = None) -> None:
    journal.archived_at = _to_utc(archived_at or _now_local())


def _daily_rollup_boundary(now: datetime) -> datetime:
    current = _as_local(now)
    if current is None:
        raise ValueError("now is required")
    return current.replace(
        hour=DEFAULT_DAILY_ROLLUP_MINUTE // 60,
        minute=DEFAULT_DAILY_ROLLUP_MINUTE % 60,
        second=0,
        microsecond=0,
    )


def _daily_window_for_boundary(boundary: datetime) -> tuple[datetime, datetime, date]:
    window_start = _local_day_start(boundary)
    window_end = boundary + timedelta(minutes=1)
    return window_start, window_end, boundary.date()


def _daily_prune_boundary(now: datetime) -> datetime:
    current = _as_local(now)
    if current is None:
        raise ValueError("now is required")
    return current.replace(
        hour=DEFAULT_DAILY_PRUNE_MINUTE // 60,
        minute=DEFAULT_DAILY_PRUNE_MINUTE % 60,
        second=0,
        microsecond=0,
    )


def _prune_cutoff_for_boundary(boundary: datetime) -> datetime:
    previous_day = boundary.date() - timedelta(days=1)
    return boundary.replace(
        year=previous_day.year,
        month=previous_day.month,
        day=previous_day.day,
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    ) + timedelta(microseconds=1)


def _delete_activities_before(user_id: int, cutoff: datetime) -> int:
    return (
        AIAgentActivity.query.filter(
            AIAgentActivity.user_id == user_id,
            AIAgentActivity.created_at < cutoff,
        ).delete(synchronize_session=False)
    )


def summarize_and_prune_user_activities(
    user_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    setting = get_or_create_setting(user_id)
    if not setting.enabled:
        return {"ok": False, "skipped": True, "reason": "disabled"}

    current = _as_local(now or _now_local())
    if current is None:
        return {"ok": False, "skipped": True, "reason": "no_time"}

    boundary = _daily_rollup_boundary(current)
    if not force:
        last_rollup = _as_local(setting.last_rollup_at)
        if current < boundary:
            return {"ok": True, "skipped": True, "reason": "not_due"}
        if last_rollup is not None and last_rollup >= boundary:
            return {"ok": True, "skipped": True, "reason": "not_due"}

    window_start, window_end, rollup_date = _daily_window_for_boundary(boundary)
    existing_daily = _current_daily_journal(user_id, rollup_date)
    if existing_daily is not None and existing_daily.archived_at is not None:
        setting.last_rollup_at = _to_utc(boundary)
        db.session.commit()
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_generated",
            "journal_date": rollup_date.isoformat(),
            "deleted": 0,
        }

    stored_start = _to_utc(window_start)
    stored_end = _to_utc(window_end)
    activities = activities_in_window(user_id, stored_start, stored_end)
    if not activities:
        if existing_daily is not None and existing_daily.archived_at is None:
            archive_daily_journal(existing_daily, archived_at=boundary)
        setting.last_rollup_at = _to_utc(boundary)
        db.session.commit()
        return {
            "ok": True,
            "skipped": True,
            "reason": "empty_window",
            "window_start": stored_start.isoformat(),
            "window_end": stored_end.isoformat(),
            "deleted": 0,
        }

    content = generate_journal(
        setting,
        "today",
        activities,
        previous_daily_content=existing_daily.content if existing_daily else None,
        window_label=f"{window_start.strftime('%H:%M')} - {(window_end - timedelta(minutes=1)).strftime('%H:%M')}",
    )
    journal = save_generated_journal(
        user_id,
        "daily",
        content,
        start_date=rollup_date,
        end_date=rollup_date,
    )
    archive_daily_journal(journal, archived_at=boundary)

    setting.last_rollup_at = _to_utc(boundary)
    db.session.commit()
    return {
        "ok": True,
        "skipped": False,
        "journal_id": journal.id,
        "journal_period": journal.period,
        "content": content,
        "window_start": stored_start.isoformat(),
        "window_end": stored_end.isoformat(),
        "slot": format_daily_rollup_time(DEFAULT_DAILY_ROLLUP_MINUTE),
        "activity_count": len(activities),
        "deleted": 0,
    }


def prune_previous_day_activities(
    user_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    setting = get_or_create_setting(user_id)
    if not setting.enabled:
        return {"ok": False, "skipped": True, "reason": "disabled"}

    current = _as_local(now or _now_local())
    if current is None:
        return {"ok": False, "skipped": True, "reason": "no_time"}

    boundary = _daily_prune_boundary(current)
    if not force and (
        current < boundary
        or current >= boundary + timedelta(minutes=DEFAULT_DAILY_PRUNE_WINDOW_MINUTES)
    ):
        return {"ok": True, "skipped": True, "reason": "not_prune_time"}

    cutoff = _prune_cutoff_for_boundary(boundary)
    deleted = _delete_activities_before(user_id, _to_utc(cutoff))
    db.session.commit()
    return {
        "ok": True,
        "skipped": False,
        "deleted": deleted,
        "cutoff": _to_utc(cutoff).isoformat(),
        "slot": format_fixed_prune_time(),
    }


def run_due_daily_rollups(user_id: int, *, now: datetime | None = None, force: bool = False) -> list[dict]:
    current = _as_local(now or _now_local())
    if current is None:
        return [{"ok": False, "skipped": True, "reason": "no_time"}]

    daily_result = summarize_and_prune_user_activities(user_id, now=current, force=force)
    prune_result = prune_previous_day_activities(user_id, now=current, force=force)
    return [daily_result, prune_result]


def generate_weekly_journal_from_recent_daily(
    user_id: int,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict:
    setting = get_or_create_setting(user_id)
    if not setting.enabled:
        return {"ok": False, "skipped": True, "reason": "disabled"}

    current = _as_local(now or _now_local())
    if current is None:
        return {"ok": False, "skipped": True, "reason": "no_time"}

    current_end_date = current.date()
    current_start_date = current_end_date - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
    existing_current = AIAgentJournal.query.filter_by(
        user_id=user_id,
        period="weekly",
        start_date=current_start_date,
    ).first()
    if existing_current is not None and not force:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_generated",
            "journal_id": existing_current.id,
        }

    boundary = _daily_rollup_boundary(current)
    if not force and (current.weekday() != 6 or current < boundary):
        return {"ok": True, "skipped": True, "reason": "not_weekly_slot"}

    effective = current.replace(second=0, microsecond=0) if force else boundary
    end_date = effective.date()
    start_date = end_date - timedelta(days=WEEKLY_ROLLUP_DAYS - 1)
    existing = AIAgentJournal.query.filter_by(
        user_id=user_id,
        period="weekly",
        start_date=start_date,
    ).first()
    if existing is not None and not force:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_generated",
            "journal_id": existing.id,
        }
    journals = _archived_recent_daily_journals(user_id, end_date)
    if not journals:
        return {"ok": True, "skipped": True, "reason": "no_archived_daily_journals"}

    content = generate_journal(
        setting,
        "week",
        [],
        source_journals=journals,
    )
    journal = save_generated_journal(
        user_id,
        "weekly",
        content,
        start_date=start_date,
        end_date=end_date,
    )
    for item in journals:
        archive_daily_journal(item, archived_at=effective)
    db.session.commit()
    return {
        "ok": True,
        "skipped": False,
        "journal_id": journal.id,
        "journal_period": journal.period,
        "content": content,
        "source_count": len(journals),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def run_scheduled_rollups(now: datetime | None = None) -> list[dict]:
    current = _as_local(now or _now_local())
    results: list[dict] = []
    for setting in AIAgentSetting.query.filter_by(enabled=True).all():
        daily_results = run_due_daily_rollups(setting.user_id, now=current)
        results.append({"user_id": setting.user_id, "kind": "daily", "result": daily_results})
        weekly_result = generate_weekly_journal_from_recent_daily(setting.user_id, now=current)
        results.append({"user_id": setting.user_id, "kind": "weekly", "result": weekly_result})
    return results
