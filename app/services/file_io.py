"""Helpers for persisting uploaded attachment files."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable

from flask import current_app
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Document, File


def save_uploaded_files(
    document: Document,
    files: Iterable,
    user_id: int,
) -> tuple[list[Path], list[str]]:
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    user_dir = upload_root / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    skipped: list[str] = []
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        ext = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
        if ext not in allowed:
            skipped.append(uploaded.filename)
            continue

        original = secure_filename(uploaded.filename) or "file"
        stored = f"{uuid.uuid4().hex}.{ext}"
        target = user_dir / stored
        uploaded.save(target)
        saved.append(target)

        db.session.add(
            File(
                document_id=document.id,
                file_path=str(Path(str(user_id)) / stored).replace("\\", "/"),
                original_name=original,
                file_size=target.stat().st_size,
                mime_type=uploaded.mimetype or "",
            )
        )

    return saved, skipped
