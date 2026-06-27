from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.services.ai_agent import run_scheduled_rollups


def main() -> None:
    app = create_app(os.getenv("FLASK_ENV", "dev"))
    with app.app_context():
        run_scheduled_rollups()
        db.session.commit()


if __name__ == "__main__":
    main()
