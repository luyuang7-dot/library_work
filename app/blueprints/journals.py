from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, timedelta

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from ..services.ai_agent import list_month_daily_journals, list_month_weekly_journals

bp = Blueprint("journals", __name__)


def _resolve_year_month() -> tuple[int, int]:
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
    except (TypeError, ValueError):
        year = today.year
    try:
        month = int(request.args.get("month", today.month))
    except (TypeError, ValueError):
        month = today.month
    year = min(max(year, 1970), 2100)
    month = min(max(month, 1), 12)
    return year, month


def _build_calendar_weeks(year: int, month: int):
    first_day = date(year, month, 1)
    first_week_start = first_day - timedelta(days=first_day.weekday())
    month_last_day = date(year, month, calendar.monthrange(year, month)[1])
    last_week_end = month_last_day + timedelta(days=6 - month_last_day.weekday())

    days = []
    cursor = first_week_start
    while cursor <= last_week_end:
        days.append(cursor)
        cursor += timedelta(days=1)
    weeks = [days[i : i + 7] for i in range(0, len(days), 7)]
    return weeks, first_week_start, last_week_end


def _summarize(content: str, limit: int = 88) -> str:
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text = text.replace("`", "").replace("*", "").replace("_", "")
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _cn_date_label(value: date) -> str:
    return f"{value.month}月{value.day}日"


def _kaomoji(seed: str) -> str:
    options = [
        "(｡･ω･｡)",
        "(=^･ω･^=)",
        "(ﾉ◕ヮ◕)ﾉ",
        "(づ｡◕‿‿◕｡)づ",
        "(⁎⁍̴̛ᴗ⁍̴̛⁎)",
        "(｀・ω・´)",
    ]
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    return options[digest[0] % len(options)]


@bp.route("/")
@login_required
def index():
    year, month = _resolve_year_month()
    weeks, range_start, range_end = _build_calendar_weeks(year, month)

    daily = list_month_daily_journals(current_user.id, year, month)
    daily_map = {
        item.start_date: {
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "summary": _summarize(item.content),
            "label": f"{_cn_date_label(item.start_date)}日志",
            "emoji": _kaomoji(item.content or item.title or str(item.start_date)),
        }
        for item in daily
    }

    weekly = list_month_weekly_journals(current_user.id, range_start, range_end)
    weekly_map = {
        item.start_date: {
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "summary": _summarize(item.content, limit=110),
            "label": f"{_cn_date_label(item.start_date)}-{_cn_date_label(item.end_date)}周札",
            "emoji": _kaomoji((item.content or item.title or str(item.start_date)) + "weekly"),
        }
        for item in weekly
    }

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return render_template(
        "journals/index.html",
        year=year,
        month=month,
        month_label=f"{year}-{month:02d}",
        weeks=weeks,
        daily_map=daily_map,
        weekly_map=weekly_map,
        today=date.today(),
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
    )
