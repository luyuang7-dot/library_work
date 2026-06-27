import io
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
    root = Path(tempfile.gettempdir()) / "personal_library_test_runtime"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def create_approved_user(
    username: str,
    password: str = "pw123456",
    email: str | None = None,
) -> int:
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        is_admin=False,
        is_approved=True,
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
def user(app):
    with app.app_context():
        return create_approved_user("tester", email="t@example.com")


@pytest.fixture
def login_client(client, app):
    with app.app_context():
        if User.query.filter_by(username="tester").first() is None:
            user = User(
                username="tester",
                email="t@example.com",
                is_admin=False,
                is_approved=True,
            )
            user.set_password("pw123456")
            db.session.add(user)
            db.session.commit()
    client.post(
        "/auth/login",
        data={"username": "tester", "password": "pw123456"},
        follow_redirects=False,
    )
    return client


@pytest.fixture
def approved_user_factory(app):
    def _create(username: str, password: str = "pw123456", email: str | None = None):
        with app.app_context():
            return create_approved_user(username, password=password, email=email)

    return _create


@pytest.fixture
def login_as(client):
    def _login(username: str, password: str = "pw123456"):
        return client.post(
            "/auth/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    return _login


@pytest.fixture
def seeded_user_id(app, login_client):
    with app.app_context():
        user = User.query.filter_by(username="tester").first()
        return user.id


_TINY_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


@pytest.fixture
def tiny_pdf_bytes():
    return _TINY_PDF


@pytest.fixture
def upload_pdf(tiny_pdf_bytes):
    def _make(filename="sample.pdf"):
        return (io.BytesIO(tiny_pdf_bytes), filename)

    return _make


@pytest.fixture
def mock_mineru(monkeypatch):
    calls = []

    def fake_parse_pdf(base_url, file_bytes, filename, **kwargs):
        calls.append({"url": base_url, "filename": filename, "kwargs": kwargs})
        return {"md": f"# {filename}\n\nFake markdown body.", "content_list": []}

    from app.services import mineru_client

    monkeypatch.setattr(mineru_client, "parse_pdf", fake_parse_pdf)
    return calls
