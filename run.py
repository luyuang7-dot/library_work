import os

ENV = os.getenv("FLASK_ENV", "dev")
if ENV != "dev":
    raise SystemExit(
        "run.py is for local development only. Use gunicorn/systemd in production."
    )

from app import create_app

app = create_app(ENV)

if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
        debug=bool(app.config.get("DEBUG", False)),
    )
