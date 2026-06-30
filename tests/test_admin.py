from __future__ import annotations

from app.extensions import db
from app.models import User


def test_admin_console_requires_review_permission(client, approved_user_factory, login_as):
    approved_user_factory("plain-user")
    login_as("plain-user")
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 403


def test_primary_admin_can_approve_pending_user(client, app, login_as, approved_user_factory):
    with app.app_context():
        admin_id = approved_user_factory("chief-admin", is_admin=True, can_review_registrations=True)
        pending_id = approved_user_factory(
            "pending-user",
            is_approved=False,
            approval_status="pending",
        )
        assert admin_id

    login_as("chief-admin")
    response = client.post(f"/admin/users/{pending_id}/approve", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, pending_id)
        assert user is not None
        assert user.is_approved is True
        assert user.approval_status == "approved"


def test_rejected_user_cannot_log_in(client, app, approved_user_factory):
    with app.app_context():
        approved_user_factory(
            "rejected-user",
            is_approved=False,
            approval_status="rejected",
        )

    response = client.post(
        "/auth/login",
        data={"username": "rejected-user", "password": "Password1!"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_primary_admin_can_grant_secondary_admin(client, app, login_as, approved_user_factory):
    with app.app_context():
        approved_user_factory("chief-admin", is_admin=True, can_review_registrations=True)
        target_id = approved_user_factory("review-target")

    login_as("chief-admin")
    response = client.post(f"/admin/users/{target_id}/grant-reviewer", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target is not None
        assert target.is_admin is False
        assert target.can_review_registrations is True


def test_secondary_admin_cannot_grant_roles(client, app, login_as, approved_user_factory):
    with app.app_context():
        approved_user_factory("secondary-admin", can_review_registrations=True)
        target_id = approved_user_factory("target-user")

    login_as("secondary-admin")
    response = client.post(f"/admin/users/{target_id}/grant-reviewer", follow_redirects=False)
    assert response.status_code == 403

    with app.app_context():
        target = db.session.get(User, target_id)
        assert target is not None
        assert target.can_review_registrations is False


def test_secondary_admin_can_approve_pending_user(client, app, login_as, approved_user_factory):
    with app.app_context():
        approved_user_factory("secondary-admin", can_review_registrations=True)
        pending_id = approved_user_factory(
            "queued-user",
            is_approved=False,
            approval_status="pending",
        )

    login_as("secondary-admin")
    response = client.post(f"/admin/users/{pending_id}/approve", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, pending_id)
        assert user is not None
        assert user.is_approved is True
        assert user.approval_status == "approved"
