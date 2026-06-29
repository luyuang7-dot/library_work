import json
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import event
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .security import (
    decrypt_ai_agent_api_key,
    encrypt_ai_agent_api_key,
    is_ai_agent_api_key_encrypted,
)


def _utcnow():
    return datetime.now(timezone.utc)


def _utc_naive(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(128), unique=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    can_review_registrations = db.Column(db.Boolean, nullable=False, default=False)
    is_approved = db.Column(db.Boolean, nullable=False, default=False)
    approval_status = db.Column(
        db.Enum("pending", "approved", "rejected", name="user_approval_status"),
        nullable=False,
        default="pending",
    )
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    documents = db.relationship(
        "Document",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    categories = db.relationship(
        "Category",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def approval_status_value(self) -> str:
        if self.is_approved:
            return "approved"
        status = (self.approval_status or "").strip().lower()
        if status == "rejected":
            return "rejected"
        return "pending"

    @property
    def can_review_registrations_effective(self) -> bool:
        return bool(self.is_admin or self.can_review_registrations)

    @property
    def is_secondary_admin(self) -> bool:
        return bool(self.can_review_registrations and not self.is_admin)


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    name = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    owner = db.relationship("User", back_populates="categories")
    children = db.relationship(
        "Category",
        backref=db.backref("parent", remote_side=[id]),
    )
    documents = db.relationship("Document", back_populates="category")


class Publisher(db.Model):
    __tablename__ = "publishers"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False)
    address = db.Column(db.String(256))
    website = db.Column(db.String(256))

    sources = db.relationship("Source", back_populates="publisher")

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_publisher_user_name"),
    )


class Source(db.Model):
    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False, index=True)
    type = db.Column(
        db.Enum("journal", "conference", "book_series", "other", name="source_type"),
        nullable=False,
        default="journal",
    )
    publisher_id = db.Column(db.Integer, db.ForeignKey("publishers.id"), nullable=True)
    issn = db.Column(db.String(20))

    publisher = db.relationship("Publisher", back_populates="sources")
    documents = db.relationship("Document", back_populates="source")

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", "type", name="uq_source_user_name_type"),
    )


class Affiliation(db.Model):
    __tablename__ = "affiliations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(256), nullable=False)
    address = db.Column(db.String(256))

    authors = db.relationship(
        "Author",
        secondary="author_affiliations",
        back_populates="affiliations",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_affiliation_user_name"),
    )


class Author(db.Model):
    __tablename__ = "authors"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    code = db.Column(db.SmallInteger, nullable=False, default=1)

    affiliations = db.relationship(
        "Affiliation",
        secondary="author_affiliations",
        back_populates="authors",
    )
    document_links = db.relationship(
        "DocumentAuthor",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", "code", name="uq_author_user_name_code"),
    )

    @property
    def display_name(self) -> str:
        return f"{self.name}#{self.code}"


class AuthorCode(db.Model):
    __tablename__ = "author_codes"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    name = db.Column(db.String(128), primary_key=True)
    next_code = db.Column(db.SmallInteger, nullable=False, default=2)


class AuthorAffiliation(db.Model):
    __tablename__ = "author_affiliations"

    author_id = db.Column(db.Integer, db.ForeignKey("authors.id"), primary_key=True)
    affiliation_id = db.Column(db.Integer, db.ForeignKey("affiliations.id"), primary_key=True)


class Keyword(db.Model):
    __tablename__ = "keywords"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)

    documents = db.relationship(
        "Document",
        secondary="document_keywords",
        back_populates="keywords",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_keyword_user_name"),
    )


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)

    documents = db.relationship(
        "Document",
        secondary="document_tags",
        back_populates="tags",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=True)

    title = db.Column(db.String(512), nullable=False)
    abstract = db.Column(db.Text)
    document_type = db.Column(
        db.Enum(
            "journal_article",
            "conference_paper",
            "book",
            "thesis",
            "report",
            "other",
            name="document_type",
        ),
        default="journal_article",
        nullable=False,
    )
    publication_year = db.Column(db.SmallInteger)
    volume = db.Column(db.String(32))
    issue = db.Column(db.String(32))
    pages = db.Column(db.String(32))
    doi = db.Column(db.String(128), index=True)
    notes = db.Column(db.Text)
    rating = db.Column(db.SmallInteger)
    reading_status = db.Column(
        db.Enum("unread", "reading", "read", name="reading_status"),
        default="unread",
        nullable=False,
    )
    barcode = db.Column(db.String(64), nullable=True)
    copy_no = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    owner = db.relationship("User", back_populates="documents")
    category = db.relationship("Category", back_populates="documents")
    source = db.relationship("Source", back_populates="documents")
    author_links = db.relationship(
        "DocumentAuthor",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentAuthor.author_order",
    )
    keywords = db.relationship(
        "Keyword",
        secondary="document_keywords",
        back_populates="documents",
    )
    tags = db.relationship(
        "Tag",
        secondary="document_tags",
        back_populates="documents",
    )
    files = db.relationship(
        "File",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "barcode", name="uq_document_user_barcode"),
        db.UniqueConstraint("user_id", "copy_no", name="uq_document_user_copy_no"),
    )

    @property
    def authors(self):
        return [link.author for link in self.author_links]

    @property
    def authors_display(self) -> str:
        return ", ".join(author.name for author in self.authors)

    @property
    def keywords_display(self) -> str:
        return ", ".join(keyword.name for keyword in self.keywords)

    @property
    def tags_display(self) -> str:
        return ", ".join(tag.name for tag in self.tags)


class DocumentAuthor(db.Model):
    __tablename__ = "document_authors"

    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("authors.id"), primary_key=True)
    author_order = db.Column(db.SmallInteger, nullable=False, default=1)

    document = db.relationship("Document", back_populates="author_links")
    author = db.relationship("Author", back_populates="document_links")


class DocumentKeyword(db.Model):
    __tablename__ = "document_keywords"

    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)
    keyword_id = db.Column(db.Integer, db.ForeignKey("keywords.id"), primary_key=True)


class DocumentTag(db.Model):
    __tablename__ = "document_tags"

    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)


class UserSetting(db.Model):
    __tablename__ = "user_settings"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    mineru_url = db.Column(db.String(256))

    user = db.relationship(
        "User",
        backref=db.backref("settings", uselist=False, cascade="all, delete-orphan"),
    )


class AIAgentSetting(db.Model):
    __tablename__ = "ai_agent_settings"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    agent_name = db.Column(db.String(64), nullable=False, default="Eyjafjalla")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    api_url = db.Column(db.String(512))
    _api_key = db.Column("api_key", db.Text)
    model = db.Column(db.String(64))
    user_preference = db.Column(db.String(500), nullable=False, default="")
    daily_rollup_minute = db.Column(db.Integer, nullable=False, default=23 * 60 + 59)
    last_rollup_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    user = db.relationship(
        "User",
        backref=db.backref("ai_agent_setting", uselist=False, cascade="all, delete-orphan"),
    )

    @property
    def api_key(self) -> str | None:
        return decrypt_ai_agent_api_key(self._api_key)

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        self._api_key = encrypt_ai_agent_api_key(value)

    @property
    def api_key_ciphertext(self) -> str | None:
        return self._api_key

    def has_legacy_plaintext_api_key(self) -> bool:
        return bool(self._api_key) and not is_ai_agent_api_key_encrypted(self._api_key)

    def migrate_api_key_to_encrypted(self) -> bool:
        if not self.has_legacy_plaintext_api_key():
            return False
        legacy_plain = self._api_key
        self.api_key = legacy_plain
        return True


class AIAgentActivity(db.Model):
    __tablename__ = "ai_agent_activities"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    label = db.Column(db.String(256), nullable=False)
    metadata_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)

    user = db.relationship(
        "User",
        backref=db.backref("ai_agent_activities", cascade="all, delete-orphan"),
    )


class AIAgentJournal(db.Model):
    __tablename__ = "ai_agent_journals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    period = db.Column(
        db.Enum("daily", "weekly", name="ai_journal_period"),
        nullable=False,
        index=True,
    )
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    title = db.Column(db.String(128), nullable=False)
    content = db.Column(db.Text, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)
    updated_at = db.Column(
        db.DateTime,
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    user = db.relationship(
        "User",
        backref=db.backref("ai_agent_journals", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "period",
            "start_date",
            name="uq_ai_journal_user_period_start",
        ),
    )


class MergeAudit(db.Model):
    __tablename__ = "merge_audits"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(
        db.Enum("merge_apply", "merge_rollback", name="merge_audit_action"),
        nullable=False,
    )
    target_audit_id = db.Column(db.Integer, db.ForeignKey("merge_audits.id"), nullable=True, index=True)
    summary_json = db.Column(db.Text, nullable=False, default="{}")
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    rolled_back_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, nullable=False, index=True)

    target_audit = db.relationship("MergeAudit", remote_side=[id], uselist=False)


class File(db.Model):
    __tablename__ = "files"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id"), nullable=False, index=True)
    file_path = db.Column(db.String(512), nullable=False)
    original_name = db.Column(db.String(256), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(64))
    uploaded_at = db.Column(db.DateTime, default=_utcnow, nullable=False)

    document = db.relationship("Document", back_populates="files")


@event.listens_for(AIAgentActivity, "before_insert")
@event.listens_for(AIAgentActivity, "before_update")
def _normalize_ai_agent_activity_timestamps(_mapper, _connection, target) -> None:
    target.created_at = _utc_naive(target.created_at)


@event.listens_for(AIAgentJournal, "before_insert")
@event.listens_for(AIAgentJournal, "before_update")
def _normalize_ai_agent_journal_timestamps(_mapper, _connection, target) -> None:
    target.archived_at = _utc_naive(target.archived_at)
    target.created_at = _utc_naive(target.created_at)
    target.updated_at = _utc_naive(target.updated_at)


@event.listens_for(AIAgentSetting, "before_insert")
@event.listens_for(AIAgentSetting, "before_update")
def _normalize_ai_agent_setting_timestamps(_mapper, _connection, target) -> None:
    target.last_rollup_at = _utc_naive(target.last_rollup_at)
    target.created_at = _utc_naive(target.created_at)
    target.updated_at = _utc_naive(target.updated_at)


@event.listens_for(MergeAudit, "before_insert")
@event.listens_for(MergeAudit, "before_update")
def _normalize_merge_audit_timestamps(_mapper, _connection, target) -> None:
    target.rolled_back_at = _utc_naive(target.rolled_back_at)
    target.created_at = _utc_naive(target.created_at)


@event.listens_for(Document, "before_insert")
@event.listens_for(Document, "before_update")
def _normalize_document_timestamps(_mapper, _connection, target) -> None:
    target.created_at = _utc_naive(target.created_at)
    target.updated_at = _utc_naive(target.updated_at)


@event.listens_for(Category, "before_insert")
@event.listens_for(Category, "before_update")
def _normalize_category_timestamps(_mapper, _connection, target) -> None:
    target.created_at = _utc_naive(target.created_at)


@event.listens_for(File, "before_insert")
@event.listens_for(File, "before_update")
def _normalize_file_timestamps(_mapper, _connection, target) -> None:
    target.uploaded_at = _utc_naive(target.uploaded_at)

