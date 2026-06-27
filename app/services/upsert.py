import re
from typing import List, Optional, Union

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Author, AuthorCode, Affiliation, Keyword, Publisher, Source, Tag


# ---------- Author ----------

def get_or_create_author(
    name: str, user_id: int, code: Optional[int] = None
) -> Author:
    """Strict form-input path.

    - ``code`` is an int: must match an existing (user_id, name, code) row.
    - ``code`` is None: name must be brand new for this user. If the user
      already has any record with this name, raises.
    """
    name = name.strip()
    if code is not None:
        author = Author.query.filter_by(
            user_id=user_id, name=name, code=code
        ).first()
        if author is None:
            raise ValueError(f"作者『{name}#{code}』在你的库中不存在")
        return author

    counter = db.session.get(AuthorCode, (user_id, name))
    if counter is not None:
        n = counter.next_code - 1
        raise ValueError(
            f"作者『{name}』在你的库中已有 {n} 条记录，请在表单中选择编号或标记为新人"
        )

    author = Author(user_id=user_id, name=name, code=1)
    db.session.add(author)
    db.session.add(AuthorCode(user_id=user_id, name=name, next_code=2))
    db.session.flush()
    return author


def allocate_new_author(name: str, user_id: int) -> Author:
    """Explicitly allocate a new code for a (possibly existing) name."""
    name = name.strip()
    for _attempt in range(3):
        try:
            counter = (
                AuthorCode.query.filter_by(user_id=user_id, name=name)
                .with_for_update()
                .first()
            )
            if counter is None:
                author = Author(user_id=user_id, name=name, code=1)
                db.session.add(author)
                db.session.add(AuthorCode(user_id=user_id, name=name, next_code=2))
            else:
                author = Author(user_id=user_id, name=name, code=counter.next_code)
                counter.next_code += 1
                db.session.add(author)
            db.session.flush()
            return author
        except IntegrityError:
            db.session.rollback()
    raise ValueError(f"Failed to allocate a unique author code for {name!r}.")


def get_or_create_author_lenient(name: str, user_id: int) -> Author:
    """Bulk-import path (BibTeX).

    Reuses the lowest-code same-name author within this user's scope; if none
    exists, creates code=1.
    """
    name = name.strip()
    author = (
        Author.query.filter_by(user_id=user_id, name=name)
        .order_by(Author.code).first()
    )
    if author is not None:
        return author
    return get_or_create_author(name, user_id)


def peek_authors_by_name(name: str, user_id: int) -> List[Author]:
    name = name.strip()
    if not name:
        return []
    return (
        Author.query.filter_by(user_id=user_id, name=name)
        .order_by(Author.code).all()
    )


# ---------- Affiliation / Keyword / Publisher / Source ----------

def get_or_create_affiliation(name: str, user_id: int) -> Affiliation:
    name = name.strip()
    aff = Affiliation.query.filter_by(user_id=user_id, name=name).first()
    if aff:
        return aff
    aff = Affiliation(user_id=user_id, name=name)
    db.session.add(aff)
    db.session.flush()
    return aff


def get_or_create_keyword(name: str, user_id: int) -> Keyword:
    name = name.strip()
    kw = Keyword.query.filter_by(user_id=user_id, name=name).first()
    if kw:
        return kw
    kw = Keyword(user_id=user_id, name=name)
    db.session.add(kw)
    db.session.flush()
    return kw


def get_or_create_tag(name: str, user_id: int) -> Tag:
    name = name.strip()
    tag = Tag.query.filter_by(user_id=user_id, name=name).first()
    if tag:
        return tag
    tag = Tag(user_id=user_id, name=name)
    db.session.add(tag)
    db.session.flush()
    return tag


def get_or_create_publisher(name: str, user_id: int) -> Optional[Publisher]:
    if not name or not name.strip():
        return None
    name = name.strip()
    pub = Publisher.query.filter_by(user_id=user_id, name=name).first()
    if pub:
        return pub
    pub = Publisher(user_id=user_id, name=name)
    db.session.add(pub)
    db.session.flush()
    return pub


def get_or_create_source(
    name: str,
    user_id: int,
    source_type: str = "journal",
    publisher_name: Optional[str] = None,
) -> Optional[Source]:
    if not name or not name.strip():
        return None
    name = name.strip()
    src = Source.query.filter_by(
        user_id=user_id, name=name, type=source_type
    ).first()
    if src:
        if publisher_name and not src.publisher:
            src.publisher = get_or_create_publisher(publisher_name, user_id)
        return src
    src = Source(user_id=user_id, name=name, type=source_type)
    if publisher_name:
        src.publisher = get_or_create_publisher(publisher_name, user_id)
    db.session.add(src)
    db.session.flush()
    return src


def parse_csv_list(raw: str) -> List[str]:
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,;，；、]\s*", raw)]
    return [p for p in parts if p]


# ---------- Author textarea I/O ----------

_NAME_CODE_RE = re.compile(r"^(?P<name>.+?)(?:#(?P<code>\d+|new))?\s*$")


def parse_authors_field(raw: str) -> List[dict]:
    """Each line: ``Name[#code] | Affiliation1; Affiliation2``."""
    out = []
    if not raw:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        name_token = parts[0]
        m = _NAME_CODE_RE.match(name_token)
        if not m:
            continue
        name = m.group("name").strip()
        code_raw = m.group("code")
        if code_raw is None:
            code: Union[int, str, None] = None
        elif code_raw == "new":
            code = "new"
        else:
            code = int(code_raw)
        affs = parse_csv_list(parts[1]) if len(parts) > 1 else []
        out.append({"name": name, "code": code, "affiliations": affs})
    return out


def authors_field_to_text(author_links) -> str:
    """Produce the textarea content for editing. Always emits ``#code``."""
    lines = []
    for link in author_links:
        a = link.author
        affs = "; ".join(af.name for af in a.affiliations)
        head = f"{a.name}#{a.code}"
        lines.append(f"{head} | {affs}" if affs else head)
    return "\n".join(lines)
