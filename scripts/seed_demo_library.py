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
TOPIC_GROUPS = [
    {
        "root": "\u6570\u636e\u5e93\u7cfb\u7edf",
        "children": [
            {
                "query": "database transactions",
                "category": "\u4e8b\u52a1\u5904\u7406",
                "tags": ["\u6570\u636e\u5e93", "SQL", "\u4e8b\u52a1", "\u7d22\u5f15", "\u67e5\u8be2\u4f18\u5316"],
                "keywords": ["database", "transaction", "index", "query optimization"],
            },
            {
                "query": "database indexing and query optimization",
                "category": "\u67e5\u8be2\u4f18\u5316",
                "tags": ["\u6570\u636e\u5e93", "SQL", "\u4f18\u5316", "\u5f15\u64ce", "\u7d22\u5f15"],
                "keywords": ["database", "optimization", "index", "query"],
            },
        ],
    },
    {
        "root": "\u4fe1\u606f\u68c0\u7d22",
        "children": [
            {
                "query": "information retrieval ranking",
                "category": "\u68c0\u7d22\u6392\u5e8f",
                "tags": ["\u68c0\u7d22", "\u63a8\u8350", "\u6392\u5e8f", "\u6587\u672c\u5904\u7406", "\u641c\u7d22"],
                "keywords": ["retrieval", "ranking", "search", "text mining"],
            },
            {
                "query": "recommender systems information retrieval",
                "category": "\u63a8\u8350\u7cfb\u7edf",
                "tags": ["\u63a8\u8350", "\u68c0\u7d22", "\u7528\u6237\u6a21\u578b", "\u7279\u5f81", "\u8bc4\u4f30"],
                "keywords": ["recommendation", "retrieval", "feature", "evaluation"],
            },
        ],
    },
    {
        "root": "\u673a\u5668\u5b66\u4e60",
        "children": [
            {
                "query": "machine learning classification",
                "category": "\u5206\u7c7b\u4e0e\u9884\u6d4b",
                "tags": ["\u673a\u5668\u5b66\u4e60", "\u6a21\u578b", "\u5206\u7c7b", "\u7279\u5f81", "\u9884\u6d4b"],
                "keywords": ["machine learning", "classification", "feature", "prediction"],
            },
            {
                "query": "feature engineering machine learning",
                "category": "\u7279\u5f81\u5de5\u7a0b",
                "tags": ["\u7279\u5f81", "\u673a\u5668\u5b66\u4e60", "\u6a21\u578b", "\u4f18\u5316", "\u8bc4\u4f30"],
                "keywords": ["feature", "engineering", "optimization", "evaluation"],
            },
        ],
    },
    {
        "root": "\u81ea\u7136\u8bed\u8a00\u5904\u7406",
        "children": [
            {
                "query": "natural language processing language model",
                "category": "\u8bed\u8a00\u6a21\u578b",
                "tags": ["NLP", "\u6587\u672c", "\u8bed\u8a00\u6a21\u578b", "\u62bd\u53d6", "\u751f\u6210"],
                "keywords": ["nlp", "language model", "extraction", "generation"],
            },
            {
                "query": "text generation natural language processing",
                "category": "\u6587\u672c\u751f\u6210",
                "tags": ["NLP", "\u751f\u6210", "\u6587\u672c", "\u8bed\u8a00\u6a21\u578b", "\u63a8\u7406"],
                "keywords": ["generation", "nlp", "text", "inference"],
            },
        ],
    },
    {
        "root": "\u8ba1\u7b97\u673a\u89c6\u89c9",
        "children": [
            {
                "query": "computer vision object detection",
                "category": "\u76ee\u6807\u68c0\u6d4b",
                "tags": ["\u89c6\u89c9", "\u56fe\u50cf", "\u68c0\u6d4b", "\u8bc6\u522b", "\u6df1\u5ea6\u5b66\u4e60"],
                "keywords": ["vision", "image", "detection", "recognition"],
            },
            {
                "query": "image recognition computer vision",
                "category": "\u56fe\u50cf\u8bc6\u522b",
                "tags": ["\u89c6\u89c9", "\u56fe\u50cf", "\u8bc6\u522b", "\u7279\u5f81", "\u6a21\u578b"],
                "keywords": ["vision", "image", "recognition", "feature"],
            },
        ],
    },
    {
        "root": "\u8f6f\u4ef6\u5de5\u7a0b",
        "children": [
            {
                "query": "software testing",
                "category": "\u8f6f\u4ef6\u6d4b\u8bd5",
                "tags": ["\u5de5\u7a0b", "\u6d4b\u8bd5", "\u4ee3\u7801", "\u7cfb\u7edf", "\u8bc4\u4f30"],
                "keywords": ["software", "testing", "code", "system", "evaluation"],
            },
            {
                "query": "software engineering empirical studies",
                "category": "\u5b9e\u8bc1\u7814\u7a76",
                "tags": ["\u5de5\u7a0b", "\u7cfb\u7edf", "\u6570\u636e", "\u8bc4\u4f30", "\u7814\u7a76"],
                "keywords": ["software", "system", "data", "evaluation", "research"],
            },
        ],
    },
]

TOPICS = [child for group in TOPIC_GROUPS for child in group["children"]]

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


def _ensure_category_row(user_id: int, name: str, parent_id: int | None = None) -> Category:
    row = Category.query.filter_by(user_id=user_id, name=name, parent_id=parent_id).first()
    if row is None:
        row = Category(user_id=user_id, name=name, parent_id=parent_id)
        db.session.add(row)
        db.session.flush()
    return row


def _build_category_tree(user_id: int) -> dict[str, Category]:
    roots = {}
    for group in TOPIC_GROUPS:
        roots[group["root"]] = _ensure_category_row(user_id, group["root"], None)
    mapping: dict[str, Category] = {}
    for group in TOPIC_GROUPS:
        root = roots[group["root"]]
        for child in group["children"]:
            mapping[child["category"]] = _ensure_category_row(user_id, child["category"], root.id)
    return mapping


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

        category_cache = _build_category_tree(user.id)
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
