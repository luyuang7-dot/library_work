"""Heuristic metadata extraction from MinerU output.

Input shape: ``{"md": str, "content_list": [{"type", "text", "text_level"}, ...]}``
Output shape: ``{"title", "authors", "affiliations", "emails", "abstract",
                  "keywords", "doi", "year", "source"}`` — every field optional.

These are pure regex / structure heuristics — no LLM call. They cover typical
first-page layouts of journal and conference papers (EN/中文). Unrecognized
fields stay empty rather than being guessed.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
AUTHOR_SPLIT_RE = re.compile(r"\s*(?:,|;| and |、|，)\s*")
EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+")

_ABSTRACT_HEADERS = ("abstract", "摘要", "摘  要")
_KEYWORDS_HEADERS = ("keywords", "key words", "index terms", "关键词", "关键字")


def _trim(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _looks_like_author_line(text: str) -> bool:
    if not text or len(text) > 400:
        return False
    if text.endswith("."):
        return False
    if any(h in text.lower() for h in ("abstract", "摘要", "introduction", "引言")):
        return False
    return len(AUTHOR_SPLIT_RE.split(text)) >= 2


def _parse_authors(line: str) -> tuple[list[str], list[str]]:
    """Split an author line into (names, emails). Strip superscripts/affil refs."""
    cleaned = re.sub(r"[\^∗\*†‡§¶]+\s*\d*", "", line)
    cleaned = re.sub(r"\(\s*\d+\s*\)", "", cleaned)
    parts = [p for p in AUTHOR_SPLIT_RE.split(cleaned) if p.strip()]
    names: list[str] = []
    emails: list[str] = []
    for p in parts:
        p = p.strip()
        em = EMAIL_RE.search(p)
        if em:
            emails.append(em.group(0))
            p = EMAIL_RE.sub("", p).strip(" ,;")
        if p and len(p) < 80 and not p[0].isdigit():
            names.append(p)
    return names, emails


def _find_title(content_list: list, md_text: str) -> Optional[str]:
    for item in content_list[:25]:
        if not isinstance(item, dict):
            continue
        text = _trim(item.get("text", ""))
        if not text:
            continue
        if item.get("text_level") == 1 and len(text) > 5:
            return text
    for line in md_text.splitlines():
        m = re.match(r"^#\s+(.+)", line)
        if m:
            t = _trim(m.group(1))
            if len(t) > 5:
                return t
    return None


def _find_authors(
    content_list: list, md_text: str, title: Optional[str]
) -> tuple[list[str], list[str], list[str]]:
    """Returns (names, affiliations, emails). Affiliations stay empty for now —
    MinerU's content_list doesn't tag them reliably enough to be worth guessing."""
    found_title = False
    for item in content_list[:40]:
        if not isinstance(item, dict):
            continue
        text = _trim(item.get("text", ""))
        if not text:
            continue
        if not found_title:
            if title and text == _trim(title):
                found_title = True
            continue
        if _looks_like_author_line(text):
            names, emails = _parse_authors(text)
            return names, [], emails

    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            for j in range(i + 1, min(i + 8, len(lines))):
                cand = _trim(lines[j])
                if cand and _looks_like_author_line(cand):
                    names, emails = _parse_authors(cand)
                    return names, [], emails
    return [], [], []


def _find_block_after_header(content_list: list, headers: tuple) -> Optional[str]:
    accumulated: list[str] = []
    capturing = False
    for item in content_list:
        if not isinstance(item, dict):
            continue
        text = _trim(item.get("text", ""))
        if not text:
            continue
        lower = text.lower()
        is_heading = item.get("text_level") in (1, 2, 3)
        if capturing:
            if is_heading:
                break
            accumulated.append(text)
            if sum(len(a) for a in accumulated) > 3000:
                break
        else:
            if is_heading and any(lower.startswith(h) for h in headers):
                capturing = True
                continue
            for h in headers:
                if lower.startswith(h):
                    rest = text[len(h) :].lstrip(":：. ").strip()
                    if rest:
                        accumulated.append(rest)
                        capturing = True
                    break
    return " ".join(accumulated).strip() if accumulated else None


def _find_abstract(content_list: list, md_text: str) -> Optional[str]:
    abs_text = _find_block_after_header(content_list, _ABSTRACT_HEADERS)
    if abs_text:
        return abs_text
    m = re.search(
        r"(?:^|\n)\s*(?:#+\s*)?(?:Abstract|摘\s*要)\s*[:：\.\n]+\s*(.+?)(?:\n\s*\n|\n\s*(?:#+\s+|Keywords|关键词))",
        md_text,
        re.IGNORECASE | re.DOTALL,
    )
    return _trim(m.group(1)) if m else None


def _find_keywords(content_list: list, md_text: str) -> list[str]:
    raw = _find_block_after_header(content_list, _KEYWORDS_HEADERS)
    if not raw:
        m = re.search(
            r"(?:Keywords?|Index Terms?|关键词|关键字)\s*[:：]\s*(.+?)(?:\n\s*\n|\n\s*#)",
            md_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            raw = m.group(1)
    if not raw:
        return []
    parts = re.split(r"[,;；,、]\s*", raw)
    parts = [_trim(p) for p in parts if p.strip()]
    return [p for p in parts if 1 < len(p) < 80]


def _find_doi(md_text: str) -> Optional[str]:
    m = DOI_RE.search(md_text)
    return m.group(0).rstrip(".,;)") if m else None


def _find_year(md_text: str, content_list: list) -> Optional[int]:
    candidates: list[int] = []
    head_blocks: list[str] = []
    for item in content_list[:30]:
        if isinstance(item, dict):
            t = _trim(item.get("text", ""))
            if t:
                head_blocks.append(t)
    head_text = "\n".join(head_blocks)
    for src in (head_text, md_text[:3000]):
        for m in YEAR_RE.finditer(src or ""):
            try:
                y = int(m.group(0))
            except (TypeError, ValueError):
                continue
            if 1950 <= y <= 2100:
                candidates.append(y)
    if not candidates:
        return None
    return Counter(candidates).most_common(1)[0][0]


def _find_source(md_text: str) -> Optional[str]:
    patterns = [
        r"Proceedings of (?:the )?([A-Z][A-Za-z0-9 &\-]+?)\b",
        r"In (?:Proceedings of |Proc\.\s*)([A-Z][A-Za-z0-9 &\-]+?)\b",
        r"(?:Journal|Transactions|Letters) of [A-Z][A-Za-z &\-]+",
        r"IEEE Transactions on [A-Z][A-Za-z &\-]+",
        r"ACM [A-Z][A-Za-z &\-]+",
    ]
    for pat in patterns:
        m = re.search(pat, md_text[:4000])
        if m:
            return _trim(m.group(0))
    return None


def extract_metadata(parsed: dict) -> dict:
    md = parsed.get("md", "") or ""
    content_list = parsed.get("content_list") or []

    title = _find_title(content_list, md)
    names, affiliations, emails = _find_authors(content_list, md, title)
    abstract = _find_abstract(content_list, md)
    keywords = _find_keywords(content_list, md)
    doi = _find_doi(md)
    year = _find_year(md, content_list)
    source = _find_source(md)

    return {
        "title": title or "",
        "authors": names,
        "affiliations": affiliations,
        "emails": emails,
        "abstract": abstract or "",
        "keywords": keywords,
        "doi": doi or "",
        "year": year,
        "source": source or "",
    }
