from datetime import datetime, timedelta

from app.extensions import db
from app.models import Document, User


def test_documents_list_paginates_at_twenty(
    app, client, approved_user_factory, login_as
):
    approved_user_factory("pager")
    login_as("pager")

    with app.app_context():
        user = User.query.filter_by(username="pager").first()
        base_time = datetime(2024, 1, 1, 0, 0, 0)
        for i in range(21):
            db.session.add(
                Document(
                    user_id=user.id,
                    title=f"Paper {i:02d}",
                    document_type="journal_article",
                    publication_year=2024,
                    reading_status="unread",
                    created_at=base_time + timedelta(seconds=i),
                    updated_at=base_time + timedelta(seconds=i),
                )
            )
        db.session.commit()

    resp = client.get("/documents/")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Paper 20" in body
    assert "Paper 01" in body
    assert "Paper 00" not in body
    assert "Next" in body

    resp = client.get("/documents/?page=2")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Paper 00" in body
    assert "Paper 20" not in body
