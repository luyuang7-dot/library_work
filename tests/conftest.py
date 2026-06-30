from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import config as app_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, _upgrade_database_to_head  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture
def tmp_path():
    root = Path(tempfile.gettempdir()) / "cloud_library_test_runtime"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def create_user(
    username: str,
    *,
    password: str = "Password1!",
    email: str | None = None,
    is_admin: bool = False,
    can_review_registrations: bool = False,
    is_approved: bool = True,
    approval_status: str = "approved",
) -> int:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        is_admin=is_admin,
        can_review_registrations=can_review_registrations,
        is_approved=is_approved,
        approval_status=approval_status,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user.id


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setattr(
        app_config.TestConfig,
        "SQLALCHEMY_DATABASE_URI",
        f"sqlite:///{db_path.as_posix()}",
    )
    monkeypatch.setattr(
        app_config.TestConfig,
        "UPLOAD_FOLDER",
        str((tmp_path / "uploads").resolve()),
    )
    monkeypatch.setattr(app_config.TestConfig, "WTF_CSRF_ENABLED", False)
    monkeypatch.setattr(app_config.TestConfig, "RATELIMIT_ENABLED", False)
    monkeypatch.setattr(app_config.TestConfig, "LOGIN_RATE_LIMIT", "999 per minute")

    app = create_app("test")
    with app.app_context():
        _upgrade_database_to_head(app)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def approved_user_factory(app):
    def _create(
        username: str,
        *,
        password: str = "Password1!",
        email: str | None = None,
        is_admin: bool = False,
        can_review_registrations: bool = False,
        is_approved: bool = True,
        approval_status: str = "approved",
    ) -> int:
        with app.app_context():
            return create_user(
                username,
                password=password,
                email=email,
                is_admin=is_admin,
                can_review_registrations=can_review_registrations,
                is_approved=is_approved,
                approval_status=approval_status,
            )

    return _create


@pytest.fixture
def login_as(client):
    def _login(username: str, password: str = "Password1!"):
        return client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    return _login


@pytest.fixture
def login_client(client, app):
    with app.app_context():
        if User.query.filter_by(username="tester").first() is None:
            create_user("tester", email="tester@example.com")
    client.post(
        "/auth/login",
        data={"username": "tester", "password": "Password1!"},
        follow_redirects=False,
    )
    return client


@pytest.fixture
def user(app):
    with app.app_context():
        return create_user("fixture-user", email="fixture@example.com")
