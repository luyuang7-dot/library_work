from typing import List, Tuple
import bibtexparser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase

from ..extensions import db
from ..models import Document, DocumentAuthor
from . import upsert


_BIB_TYPE_TO_DOCTYPE = {
    "article": "journal_article",
    "inproceedings": "conference_paper",
    "conference": "conference_paper",
    "book": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "techreport": "report",
    "misc": "other",
}

_DOCTYPE_TO_BIB_TYPE = {v: k for k, v in _BIB_TYPE_TO_DOCTYPE.items()}


def supported_entry_types() -> list[str]:
    """Return supported BibTeX entry types in stable display order."""
    return list(_BIB_TYPE_TO_DOCTYPE.keys())


def parse_entries(bib_text: str) -> list[dict]:
    """Parse .bib text into a list of entry dicts with no side effects."""
    if not bib_text or not bib_text.strip():
        return []
    parser = bibtexparser.bparser.BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    bib_db = bibtexparser.loads(bib_text, parser=parser)
    return bib_db.entries


def import_single_entry(
    entry: dict, user_id: int, category_id: int | None = None
) -> dict:
    """Persist one bibtex entry and return created/skipped outcome.

    Returns:
        {"created": Document | None, "skipped_reason": str | None}
    """
    title = entry.get("title", "").strip().strip("{}")
    if not title:
        return {"created": None, "skipped_reason": "缺少 title 字段"}

    doi = entry.get("doi", "").strip() or None
    year_raw = entry.get("year", "").strip()
    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None

    existing = None
    if doi:
        existing = Document.query.filter_by(user_id=user_id, doi=doi).first()
    if not existing:
        existing = Document.query.filter_by(
            user_id=user_id, title=title, publication_year=year
        ).first()
    if existing:
        return {
            "created": None,
            "skipped_reason": f"已存在文献 ID {existing.id}: {existing.title}",
        }

    bib_type = entry.get("ENTRYTYPE", "misc").lower()
    doc_type = _BIB_TYPE_TO_DOCTYPE.get(bib_type, "other")

    journal = entry.get("journal") or entry.get("booktitle")
    publisher = entry.get("publisher")
    source_type = (
        "journal"
        if bib_type == "article"
        else ("conference" if bib_type in ("inproceedings", "conference") else "other")
    )
    source = (
        upsert.get_or_create_source(journal, user_id, source_type, publisher)
        if journal
        else None
    )

    doc = Document(
        user_id=user_id,
        title=title,
        abstract=entry.get("abstract"),
        document_type=doc_type,
        publication_year=year,
        volume=entry.get("volume"),
        issue=entry.get("number") or entry.get("issue"),
        pages=entry.get("pages"),
        doi=doi,
        source=source,
        category_id=category_id,
    )
    db.session.add(doc)
    db.session.flush()

    authors_raw = entry.get("author", "")
    author_names = [a.strip() for a in authors_raw.split(" and ") if a.strip()]
    for i, name in enumerate(author_names, start=1):
        author = upsert.get_or_create_author_lenient(name, user_id)
        db.session.add(
            DocumentAuthor(document_id=doc.id, author_id=author.id, author_order=i)
        )

    kw_raw = entry.get("keywords", "")
    for kw_name in upsert.parse_csv_list(kw_raw):
        doc.keywords.append(upsert.get_or_create_keyword(kw_name, user_id))

    return {"created": doc, "skipped_reason": None}


def import_bibtex(
    bib_text: str, user_id: int, category_id: int | None = None
) -> Tuple[int, int]:
    """Parse a .bib string and create Documents. Returns (created, skipped)."""
    entries = parse_entries(bib_text)

    created = 0
    skipped = 0
    for entry in entries:
        result = import_single_entry(entry, user_id, category_id)
        if result["created"]:
            created += 1
        else:
            skipped += 1

    db.session.commit()
    return created, skipped


def export_bibtex(documents: List[Document]) -> str:
    out = BibDatabase()
    out.entries = []
    for doc in documents:
        bib_type = _DOCTYPE_TO_BIB_TYPE.get(doc.document_type, "misc")
        key = f"doc{doc.id}"
        entry = {"ENTRYTYPE": bib_type, "ID": key, "title": doc.title}
        if doc.authors:
            entry["author"] = " and ".join(a.name for a in doc.authors)
        if doc.publication_year:
            entry["year"] = str(doc.publication_year)
        if doc.source:
            if bib_type == "article":
                entry["journal"] = doc.source.name
            elif bib_type in ("inproceedings", "conference"):
                entry["booktitle"] = doc.source.name
            if doc.source.publisher:
                entry["publisher"] = doc.source.publisher.name
        if doc.volume:
            entry["volume"] = doc.volume
        if doc.issue:
            entry["number"] = doc.issue
        if doc.pages:
            entry["pages"] = doc.pages
        if doc.doi:
            entry["doi"] = doc.doi
        if doc.abstract:
            entry["abstract"] = doc.abstract
        if doc.keywords:
            entry["keywords"] = ", ".join(k.name for k in doc.keywords)
        out.entries.append(entry)
    writer = BibTexWriter()
    writer.indent = "  "
    return writer.write(out)
