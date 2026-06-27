# Personal Library

Version: 0.5.1

Personal Library is a Flask-based literature management system prepared for the course project. The current codebase is focused on document records, relational data management, PDF recognition, BibTeX workflows, and a usable web UI.

## Current Scope

- Structured document records with authors, affiliations, sources, publishers, keywords, tags, categories, and attachments
- PDF upload plus MinerU-based metadata recognition for single-item and batch import workflows
- Search, filtering, and bulk category operations
- BibTeX import and export
- Admin approval flow for new user registrations
- AI activity logs and journals that can be kept if the team still wants them

## SQL Usage

Yes. This project already uses SQL as a core part of the system:

- ORM layer: Flask-SQLAlchemy / SQLAlchemy
- Database engines: MySQL in normal deployment, SQLite in tests
- Migration management: Alembic
- Health check / low-level query usage: `SELECT 1` through SQLAlchemy

There are almost no hand-written `.sql` files because the project is ORM-first, but it is still a relational SQL application.

## Repository Layout

- `app/`: Flask app, models, blueprints, templates, and static assets
- `migrations/`: Alembic migration files
- `deploy/`: Nginx and systemd deployment assets
- `scripts/`: release, rollback, verification, and quality scripts
- `tests/`: pytest suite
- `docs/course_rebuild_plan.md`: rebuild plan aligned to the course deliverables

## Local Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
flask --app run:app init-db
python run.py
```

`run.py` is for local development only.

Copy `.env.example` to `.env` and adjust these values:

```env
FLASK_ENV=dev
FLASK_SECRET_KEY=replace-with-local-secret
AI_AGENT_API_KEY_ENCRYPTION_KEY=replace-with-local-ai-key
DATABASE_URL=mysql+pymysql://root:@localhost:3306/library_work?charset=utf8mb4
UPLOAD_FOLDER=uploads
REQUEST_LOGGING_ENABLED=true
REQUEST_ID_HEADER=X-Request-ID
LOGIN_RATE_LIMIT=5 per 15 minutes
DEFAULT_MINERU_URL=http://127.0.0.1:8000
```

## Database And Migrations

- The database connection comes from `DATABASE_URL`.
- Alembic is the single source of truth for schema changes.
- The repository uses a single course-project baseline migration for clean database initialization.

Common commands:

```bash
flask --app run:app init-db
flask --app run:app create-admin --username admin
flask --app run:app repair-legacy-schema
```

## PDF Recognition

- Single-document recognition endpoint: `/documents/recognize_pdf`
- Batch PDF recognition page: `/bibtex/batch`
- Default recognizer backend: MinerU, configured per user or via `DEFAULT_MINERU_URL`
- Recognized fields currently include title, authors, affiliations, emails, abstract, keywords, DOI, year, and source

## Dependency Workflow

- `requirements.in`: production input dependencies
- `requirements-dev.in`: development and test input dependencies
- `requirements.txt`: production lock file
- `requirements-dev.txt`: development / CI lock file

Install examples:

```powershell
pip install -r requirements-dev.txt
```

```bash
pip install -r requirements.txt
```

## Release Workflow

The repository keeps lightweight release and rollback scripts for the Flask application:

- `scripts/install_runtime_stack.sh`
- `scripts/package_production_release.py`
- `scripts/deploy_release.sh`
- `scripts/rollback_release.sh`
- `scripts/post_release_smoke_test.sh`
- `scripts/collect_runtime_snapshot.sh`
- `scripts/capture_post_release_evidence.sh`
- `scripts/finalize_release_record.sh`
- `python scripts/create_release_record.py`

Release records are generated into `artifacts/release_records/` on demand.

## Release Checklist

- Update `VERSION`
- Run `python scripts/check_release_readiness.py`
- Run `python scripts/run_quality_checks.py --skip-ruff --skip-pre-commit`
- Run `scripts/deploy_release.sh`
- Confirm `/healthz` returns success
- Run `scripts/post_release_smoke_test.sh`
- Run `scripts/collect_runtime_snapshot.sh`
- Prefer `scripts/finalize_release_record.sh <operator> http://127.0.0.1:8000 prod <version>`
- If you need a manual evidence flow, use `scripts/capture_post_release_evidence.sh` and then `python scripts/create_release_record.py --evidence-dir ...`

Optional flags:

- `RUN_RUNTIME_SNAPSHOT=false`
- `RUN_SMOKE_TEST=false`

## Verification

Typical checks:

```powershell
pytest -q
python scripts/run_quality_checks.py --skip-ruff --skip-pre-commit
python scripts/verify_hardening_status.py
python scripts/check_release_readiness.py
pytest -q tests/test_verify_hardening_status.py
```

## Course Rebuild Plan

The next-stage rebuild plan is documented in [docs/course_rebuild_plan.md](docs/course_rebuild_plan.md). It explains:

- which features are already aligned with the course project
- which modules should be kept
- how to rebuild the schema and business flow more cleanly around literature-management requirements

## Operational Notes

- Request tracing uses `REQUEST_ID_HEADER=X-Request-ID`
- `/healthz` returns the current application version
- If static assets do not refresh after a release, check `VERSION`, browser cache, and the Nginx path
