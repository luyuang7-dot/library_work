from __future__ import annotations

import argparse
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.models import Author, Category, Document, DocumentAuthor, Keyword, Source, Tag, User
from app.services import upsert

OPENALEX_URL = "https://api.openalex.org/works"
USER_AGENT = "Personal Library demo seeder/1.0 (mailto:demo@example.com)"
DEFAULT_USERNAME = "demo"
DEFAULT_COUNT = 1000
TOPICS = [
    {"query": "database systems", "category": "数据库系统", "tags": ["数据库", "SQL", "事务", "索引", "查询优化"], "keywords": ["database", "transaction", "index", "query optimization"]},
    {"query": "information retrieval", "category": "信息检索", "tags": ["检索", "推荐", "排序", "文本处理", "搜索"], "keywords": ["retrieval", "ranking", "search", "text mining"]},
    {"query": "machine learning", "category": "机器学习", "tags": ["机器学习", "模型", "分类", "特征", "预测"], "keywords": ["machine learning", "classification", "feature", "prediction"]},
    {"query": "natural language processing", "category": "自然语言处理", "tags": ["NLP", "文本", "语言模型", "抽取", "生成"], "keywords": ["nlp", "language model", "extraction", "generation"]},
    {"query": "computer vision", "category": "计算机视觉", "tags": ["视觉", "图像", "检测", "识别", "深度学习"], "keywords": ["vision", "image", "detection", "recognition"]},
    {"query": "software engineering", "category": "软件工程", "tags": ["工程", "测试", "代码", "系统", "评估"], "keywords": ["software", "testing", "code", "system", "evaluation"]},
]

COMMON_AUTHORS = ["Y. Zhang", "J. Wang", "X. Li", "H. Chen", "Q. Liu", "S. Wang", "K. Zhang", "M. Wang", "T. Li", "W. Chen"]
JOURNAL_NAMES = [
    "IEEE Transactions on Knowledge and Data Engineering",
    "ACM Transactions on Database Systems",
    "Information Sciences",
    "Knowledge-Based Systems",
    "Pattern Recognition",
    "Expert Systems with Applications",
    "Data & Knowledge Engineering",
]


@dataclass
class SeedItem:
    title: str
    year: int | None
    source: str
    doi: str | None
    authors: list[str]
    abstract: str
    category_name: str
    tags: list[str]
    keywords: list[str]
    rating: int
    reading_status: str


def _normalize_title(title: str) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip())
    return (title or "Untitled Paper")[:512]


def _extract_authors(item: dict, rng: random.Random) -> list[str]:
    names: list[str] = []
    for auth in item.get("authorships") or []:
        author = auth.get("author") or {}
        name = (author.get("display_name") or author.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    if len(names) >= 2:
        return names[:5]
    fallback = [rng.choice(COMMON_AUTHORS), rng.choice(COMMON_AUTHORS)]
    if rng.random() < 0.5:
        fallback.append(rng.choice(COMMON_AUTHORS))
    return list(dict.fromkeys(fallback))


def _extract_source(item: dict, rng: random.Random) -> str:
    loc = item.get("primary_location") or {}
    src = loc.get("source") or {}
    name = (src.get("display_name") or "").strip()
    return (name[:256] if name else rng.choice(JOURNAL_NAMES))


def _extract_year(item: dict) -> int | None:
    try:
        return int(item.get("publication_year") or 0) or None
    except (TypeError, ValueError):
        return None


def _extract_doi(item: dict) -> str | None:
    doi = (item.get("doi") or "").strip()
    if doi.startswith("https://doi.org/"):
        doi = doi.removeprefix("https://doi.org/")
    return doi[:128] or None


def _extract_abstract(item: dict) -> str:
    inv = item.get("abstract_inverted_index") or {}
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort()
    return " ".join(word for _, word in positions)[:4000]


def _fallback_item(topic: dict, ordinal: int, rng: random.Random) -> SeedItem:
    title = f"{topic['category']} 研究与应用综述 {ordinal}"
    return SeedItem(
        title=title,
        year=rng.randint(2014, 2025),
        source=rng.choice(JOURNAL_NAMES),
        doi=None,
        authors=list(dict.fromkeys([rng.choice(COMMON_AUTHORS), rng.choice(COMMON_AUTHORS)])),
        abstract=f"This is a synthetic abstract for {title} in the {topic['category']} topic.",
        category_name=topic["category"],
        tags=list(topic["tags"]),
        keywords=list(topic["keywords"]),
        rating=rng.randint(3, 5),
        reading_status=rng.choices(["unread", "reading", "read"], weights=[2, 2, 6])[0],
    )


def _fetch_topic_items(topic: dict, target: int, rng: random.Random) -> list[SeedItem]:
    items: list[SeedItem] = []
    seen_titles: set[str] = set()
    for page in range(1, 11):
        if len(items) >= target:
            break
        try:
            resp = requests.get(
                OPENALEX_URL,
                params={"search": topic["query"], "per-page": 200, "page": page},
                timeout=40,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            break

        for item in payload.get("results") or []:
            title = _normalize_title(item.get("display_name") or item.get("title") or "")
            if not title or title in seen_titles:
                continue
            authors = _extract_authors(item, rng)
            year = _extract_year(item)
            doi = _extract_doi(item)
            abstract = _extract_abstract(item) or f"{title} explores {topic['query']} with an emphasis on real-world application."
            rating = min(5, max(1, (5 if year and year >= 2020 else 4) + (1 if len(authors) >= 3 else 0) - (0 if doi else 1)))
            items.append(
                SeedItem(
                    title=title,
                    year=year,
                    source=_extract_source(item, rng),
                    doi=doi,
                    authors=authors[:5],
                    abstract=abstract[:4000],
                    category_name=topic["category"],
                    tags=list(topic["tags"]),
                    keywords=list(topic["keywords"]),
                    rating=rating,
                    reading_status=rng.choices(["unread", "reading", "read"], weights=[2, 3, 7])[0],
                )
            )
            seen_titles.add(title)
            if len(items) >= target:
                break

    while len(items) < target:
        items.append(_fallback_item(topic, len(items) + 1, rng))
    return items[:target]


def _ensure_row(model, **kwargs):
    row = model.query.filter_by(**kwargs).first()
    if row is None:
        row = model(**kwargs)
        db.session.add(row)
        db.session.flush()
    return row


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _clear_demo_data(user_id: int) -> None:
    for doc in Document.query.filter_by(user_id=user_id).all():
        db.session.delete(doc)
    db.session.flush()
    for model in (Category, Source, Author, Keyword, Tag):
        for row in model.query.filter_by(user_id=user_id).all():
            db.session.delete(row)
    db.session.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo user with realistic paper data.")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--env", default="prod")
    args = parser.parse_args()

    app = create_app(args.env, skip_db_checks=True)
    rng = random.Random(20260628)

    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if user is None:
            raise SystemExit(f"User {args.username!r} not found.")

        if args.clear:
            _clear_demo_data(user.id)
            db.session.commit()

        per_topic = max(1, math.ceil(args.count / len(TOPICS)))
        collected: list[SeedItem] = []
        for topic in TOPICS:
            collected.extend(_fetch_topic_items(topic, per_topic, rng))

        while len(collected) < args.count:
            collected.append(_fallback_item(rng.choice(TOPICS), len(collected) + 1, rng))

        collected = collected[:args.count]
        rng.shuffle(collected)
        for item in collected:
            item.tags = _dedupe_preserve_order(item.tags)
            item.keywords = _dedupe_preserve_order(item.keywords)
            item.authors = _dedupe_preserve_order(item.authors)

        category_cache = {
            name: _ensure_row(Category, user_id=user.id, name=name)
            for name in {item.category_name for item in collected}
        }
        tag_cache = {
            name: _ensure_row(Tag, user_id=user.id, name=name)
            for name in {tag for item in collected for tag in item.tags}
        }
        keyword_cache = {
            name: _ensure_row(Keyword, user_id=user.id, name=name)
            for name in {kw for item in collected for kw in item.keywords}
        }
        author_cache: dict[str, Author] = {}

        for index, item in enumerate(collected, start=1):
            doc = Document(
                user_id=user.id,
                title=item.title,
                abstract=item.abstract,
                publication_year=item.year,
                doi=item.doi,
                rating=item.rating,
                reading_status=item.reading_status,
                notes=f"Demo corpus #{index}",
                document_type="journal_article",
            )
            doc.category = category_cache[item.category_name]
            doc.source = upsert.get_or_create_source(item.source, user.id, "journal")
            db.session.add(doc)
            db.session.flush()

            for order, author_name in enumerate(item.authors, start=1):
                author = author_cache.get(author_name)
                if author is None:
                    author = _ensure_row(Author, user_id=user.id, name=author_name, code=1)
                    author_cache[author_name] = author
                db.session.add(DocumentAuthor(document_id=doc.id, author_id=author.id, author_order=order))

            for tag_name in item.tags:
                doc.tags.append(tag_cache[tag_name])
            for kw_name in item.keywords:
                doc.keywords.append(keyword_cache[kw_name])

        db.session.commit()
        print(f"Seeded {len(collected)} demo documents for user {user.username} (id={user.id}).")


if __name__ == "__main__":
    main()
