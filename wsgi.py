import os

from app import create_app

app = create_app(
    "prod",
    skip_db_checks=os.getenv("FLASK_SKIP_DB_CHECKS", "").strip().lower()
    in {"1", "true", "yes", "on"},
)
