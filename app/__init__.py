import logging
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import click
from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError, generate_csrf
from markupsafe import Markup
from sqlalchemy import text

from config import (
    CONFIG_MAP,
    DEFAULT_AI_AGENT_ENCRYPTION_KEY,
    DEFAULT_SECRET_KEY,
)

from .extensions import csrf, db, limiter, login_manager


class DatabaseMigrationRequired(RuntimeError):
    """Raised when the configured database is not migrated to Alembic head."""


class LocalBrowserLifecycle:
    """Tracks active local browser pages for the dev-only auto-shutdown flow."""

    def __init__(self, idle_timeout_seconds: float = 8.0) -> None:
        self.idle_timeout_seconds = max(float(idle_timeout_seconds), 1.0)
        self._lock = threading.Lock()
        self._clients: dict[str, float] = {}
        self._ever_seen_client = False

    def touch(self, client_id: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._clients[client_id] = current
            self._ever_seen_client = True
            self._prune_locked(current)
            return len(self._clients)

    def discard(self, client_id: str) -> int:
        with self._lock:
            self._clients.pop(client_id, None)
            self._prune_locked(time.time())
            return len(self._clients)

    def has_active_clients(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._prune_locked(current)
            return bool(self._clients)

    @property
    def ever_seen_client(self) -> bool:
        with self._lock:
            return self._ever_seen_client

    def _prune_locked(self, now: float) -> None:
        stale = [
            client_id
            for client_id, seen_at in self._clients.items()
            if now - seen_at > self.idle_timeout_seconds
        ]
        for client_id in stale:
            self._clients.pop(client_id, None)


def register_cli_commands(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command() -> None:
        """Apply all Alembic migrations to the configured database."""
        _upgrade_database_to_head(app)
        click.echo("Database migrations applied.")

    @app.cli.command("create-admin")
    @click.option("--username", required=True)
    @click.option("--password", required=True, hide_input=True, confirmation_prompt=True)
    @click.option("--email", default="", help="Optional email address.")
    def create_admin_command(username: str, password: str, email: str) -> None:
        from .blueprints.auth import validate_password_strength
        from .models import User

        username = username.strip()
        email = email.strip() or None
        password_error = validate_password_strength(password)
        if password_error:
            raise click.ClickException(password_error)

        with app.app_context():
            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    email=email,
                    is_admin=True,
                    can_review_registrations=True,
                    is_approved=True,
                    approval_status="approved",
                )
                user.set_password(password)
                db.session.add(user)
                action = "created"
            else:
                user.is_admin = True
                user.can_review_registrations = True
                user.is_approved = True
                user.approval_status = "approved"
                if email:
                    user.email = email
                user.set_password(password)
                action = "updated"
            db.session.commit()
        click.echo(f"Administrator {action}: {username}")

    @app.cli.command("repair-legacy-schema")
    def repair_legacy_schema_command() -> None:
        """Run one-time legacy schema repair helpers manually."""
        from .services.schema_bootstrap import (
            ensure_ai_agent_columns,
            ensure_ai_agent_settings_rows,
            ensure_document_columns,
            ensure_user_admin_columns,
        )

        with app.app_context():
            db.create_all()
            ensure_user_admin_columns(db.session)
            ensure_document_columns(db.session)
            ensure_ai_agent_columns(db.session)
            ensure_ai_agent_settings_rows(db.session)
        click.echo("Legacy schema repair completed.")

    @app.cli.command("ai-agent-rollup")
    @click.option("--user-id", type=int, required=True)
    @click.option("--force", is_flag=True, default=False)
    def ai_agent_rollup_command(user_id: int, force: bool) -> None:
        from .services.ai_agent import run_due_daily_rollups

        with app.app_context():
            result = run_due_daily_rollups(user_id, force=force)
        click.echo(result)

    @app.cli.command("ai-agent-weekly-rollup")
    @click.option("--user-id", type=int, required=True)
    @click.option("--force", is_flag=True, default=False)
    def ai_agent_weekly_rollup_command(user_id: int, force: bool) -> None:
        from .services.ai_agent import generate_weekly_journal_from_recent_daily

        with app.app_context():
            result = generate_weekly_journal_from_recent_daily(user_id, force=force)
        click.echo(result)


def create_app(env: str = "dev", *, skip_db_checks: bool = False) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(CONFIG_MAP.get(env, CONFIG_MAP["dev"]))
    _normalize_cookie_domains(app)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.instance_path, exist_ok=True)

    _configure_logging(app)
    _validate_runtime_configuration(app)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    register_cli_commands(app)
    app.extensions["local_browser_lifecycle"] = LocalBrowserLifecycle(
        app.config.get("LOCAL_BROWSER_IDLE_TIMEOUT_SECONDS", 8.0)
    )

    from . import models  # noqa: F401

    if app.config.get("REQUIRE_DB_AT_HEAD") and not skip_db_checks:
        with app.app_context():
            assert_database_is_current(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    from .blueprints.ai_agent import bp as ai_agent_bp
    from .blueprints.admin import bp as admin_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.batch_bibtex import bp as batch_bibtex_bp
    from .blueprints.bibtex import bp as bibtex_bp
    from .blueprints.categories import bp as categories_bp
    from .blueprints.documents import bp as documents_bp
    from .blueprints.journals import bp as journals_bp
    from .blueprints.library import bp as library_bp
    from .blueprints.settings import bp as settings_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(documents_bp, url_prefix="/documents")
    app.register_blueprint(categories_bp, url_prefix="/categories")
    app.register_blueprint(library_bp, url_prefix="/library")
    app.register_blueprint(bibtex_bp, url_prefix="/bibtex")
    app.register_blueprint(batch_bibtex_bp, url_prefix="/bibtex")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(ai_agent_bp, url_prefix="/ai-agent")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(journals_bp, url_prefix="/journals")

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("documents.list_documents"))
        return redirect(url_for("auth.login"))

    @app.get("/healthz")
    def healthz():
        db.session.execute(text("SELECT 1"))
        return jsonify(ok=True, status="healthy", version=app.config["APP_VERSION"])

    @app.post("/__local_dev__/browser-session")
    @csrf.exempt
    def local_dev_browser_session():
        if not app.config.get("ENABLE_LOCAL_BROWSER_LIFECYCLE"):
            return jsonify(ok=False, error="Local browser lifecycle is disabled."), 404

        payload = request.get_json(silent=True) or {}
        client_id = str(payload.get("client_id") or "").strip()
        if not client_id:
            return jsonify(ok=False, error="client_id is required."), 400

        lifecycle = app.extensions.get("local_browser_lifecycle")
        if lifecycle is None:
            return jsonify(ok=False, error="Local browser lifecycle is unavailable."), 503

        event = str(payload.get("event") or "ping").strip().lower()
        if event == "close":
            active_count = lifecycle.discard(client_id)
        else:
            active_count = lifecycle.touch(client_id)
        return jsonify(ok=True, active_clients=active_count)

    @app.before_request
    def attach_request_context():
        g.request_started_at = time.perf_counter()
        request_id_header = app.config.get("REQUEST_ID_HEADER", "X-Request-ID")
        incoming_request_id = request.headers.get(request_id_header, "").strip()
        g.request_id = incoming_request_id or uuid4().hex

    @app.context_processor
    def inject_globals():
        return {
            "app_name": "个人文献库",
            "app_version": app.config["APP_VERSION"],
            "local_browser_session_url": app.config.get("LOCAL_BROWSER_SESSION_URL", ""),
            "csrf_token": generate_csrf,
            "csrf_input": lambda: Markup(
                f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">'
            ),
        }

    @app.template_filter("tag_color")
    def tag_color(name: str) -> str:
        """Deterministically map a tag name to a palette colour so the same tag
        always renders with the same badge colour (no DB column needed)."""
        palette = (
            "gray", "blue", "purple", "amber",
            "red", "pink", "green", "teal",
        )
        digest = 0
        for char in str(name or ""):
            digest = (digest * 31 + ord(char)) & 0xFFFFFFFF
        return palette[digest % len(palette)]

    @app.after_request
    def finalize_response(response):
        response.headers.setdefault(
            app.config.get("REQUEST_ID_HEADER", "X-Request-ID"),
            getattr(g, "request_id", uuid4().hex),
        )
        _log_completed_request(app, response)
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        message = (
            "请求校验失败，CSRF 令牌缺失或无效，请刷新页面后重试。"
        )
        if _prefers_json():
            return jsonify(ok=False, error=message), 400
        return (
            render_template(
                "errors/generic.html",
                title="请求已拒绝",
                heading="请求校验失败",
                message=message,
            ),
            400,
        )

    @app.errorhandler(DatabaseMigrationRequired)
    def handle_database_migration_required(error):
        message = str(error)
        if _prefers_json():
            return jsonify(ok=False, error=message), 503
        return (
            render_template(
                "errors/generic.html",
                title="数据库需要迁移",
                heading="数据库需要迁移",
                message=message,
            ),
            503,
        )

    @app.errorhandler(404)
    def handle_not_found(_error):
        return (
            render_template(
                "errors/generic.html",
                title="页面不存在",
                heading="页面不存在",
                message="你访问的页面不存在，或已被移动。",
            ),
            404,
        )

    @app.errorhandler(403)
    def handle_forbidden(_error):
        message = "你没有权限访问此页面或执行该操作。"
        if _prefers_json():
            return jsonify(ok=False, error=message), 403
        return (
            render_template(
                "errors/generic.html",
                title="访问被拒绝",
                heading="访问被拒绝",
                message=message,
            ),
            403,
        )

    @app.errorhandler(429)
    def handle_too_many_requests(_error):
        message = "尝试次数过多，请稍后几分钟再试。"
        if _prefers_json():
            return jsonify(ok=False, error=message), 429
        return (
            render_template(
                "errors/generic.html",
                title="请求过于频繁",
                heading="尝试次数过多",
                message=message,
            ),
            429,
        )

    @app.errorhandler(500)
    def handle_server_error(error):
        app.logger.exception("Unhandled server error", exc_info=error)
        return (
            render_template(
                "errors/generic.html",
                title="服务器错误",
                heading="服务暂时异常",
                message=(
                    "服务器暂时无法完成本次请求，请稍后再试。"
                ),
            ),
            500,
        )

    return app


def _prefers_json() -> bool:
    if request.accept_mimetypes.best == "application/json":
        return True
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = True


def _normalize_cookie_domains(app: Flask) -> None:
    for key in ("SESSION_COOKIE_DOMAIN", "REMEMBER_COOKIE_DOMAIN"):
        raw = app.config.get(key)
        if isinstance(raw, str) and not raw.strip():
            app.config[key] = None


def _validate_runtime_configuration(app: Flask) -> None:
    if not app.config.get("ENFORCE_STRICT_SECRETS"):
        return

    secret_key = str(app.config.get("SECRET_KEY") or "").strip()
    if not secret_key or secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "Production requires a non-default FLASK_SECRET_KEY before startup."
        )

    encryption_key = str(app.config.get("AI_AGENT_API_KEY_ENCRYPTION_KEY") or "").strip()
    if not encryption_key or encryption_key == DEFAULT_AI_AGENT_ENCRYPTION_KEY:
        raise RuntimeError(
            "Production requires AI_AGENT_API_KEY_ENCRYPTION_KEY to be set explicitly."
        )


def _alembic_config_for_app(app: Flask):
    from alembic.config import Config

    alembic_ini = Path(app.root_path).parent / "alembic.ini"
    migration_dir = Path(app.root_path).parent / "migrations"
    if not alembic_ini.exists() or not migration_dir.exists():
        raise RuntimeError("Alembic configuration is missing.")

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(migration_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])
    if app.config.get("TESTING"):
        flask_env = "test"
    elif app.config.get("DEBUG"):
        flask_env = "dev"
    else:
        flask_env = "prod"
    alembic_cfg.set_main_option("flask_env", flask_env)
    return alembic_cfg


def _upgrade_database_to_head(app: Flask) -> None:
    from alembic import command

    alembic_cfg = _alembic_config_for_app(app)
    command.upgrade(alembic_cfg, "head")


def assert_database_is_current(app: Flask) -> None:
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext

    alembic_cfg = _alembic_config_for_app(app)
    script = ScriptDirectory.from_config(alembic_cfg)
    expected_heads = set(script.get_heads())
    current_heads = set()

    bind = db.session.get_bind()
    with bind.connect() as connection:
        context = MigrationContext.configure(connection)
        current_revision = context.get_current_revision()
        if current_revision:
            current_heads.add(current_revision)

    if current_heads != expected_heads:
        raise DatabaseMigrationRequired(
            "Database schema is not at the latest Alembic revision. "
            "Run the `init-db` command for this environment before starting the service."
        )


def _log_completed_request(app: Flask, response) -> None:
    if not app.config.get("REQUEST_LOGGING_ENABLED", True):
        return

    started_at = getattr(g, "request_started_at", None)
    duration_ms = 0
    if started_at is not None:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

    user_id = getattr(current_user, "id", None) if current_user else None
    app.logger.info(
        (
            "request_complete request_id=%s method=%s path=%s status=%s "
            "duration_ms=%s remote_addr=%s user_id=%s"
        ),
        getattr(g, "request_id", "-"),
        request.method,
        request.path,
        response.status_code,
        duration_ms,
        _get_client_ip(),
        user_id or "-",
    )


def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "-"
