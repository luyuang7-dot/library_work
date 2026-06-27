import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DEFAULT_SECRET_KEY = "dev-only-change-me"
DEFAULT_AI_AGENT_ENCRYPTION_KEY = "dev-ai-agent-encryption-key"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_app_version() -> str:
    version_file = BASE_DIR / "VERSION"
    if version_file.exists():
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    env_value = (os.getenv("APP_VERSION") or "").strip()
    if env_value:
        return env_value
    return "0.5.1"


class BaseConfig:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY)
    AI_AGENT_API_KEY_ENCRYPTION_KEY = os.getenv(
        "AI_AGENT_API_KEY_ENCRYPTION_KEY",
        DEFAULT_AI_AGENT_ENCRYPTION_KEY,
    )
    APP_VERSION = _default_app_version()
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:@localhost:3306/library_work?charset=utf8mb4",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    WTF_CSRF_ENABLED = _env_flag("WTF_CSRF_ENABLED", True)
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "3600"))
    RATELIMIT_ENABLED = _env_flag("RATELIMIT_ENABLED", True)
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5 per 15 minutes")
    REQUEST_LOGGING_ENABLED = _env_flag("REQUEST_LOGGING_ENABLED", True)
    REQUEST_ID_HEADER = os.getenv("REQUEST_ID_HEADER", "X-Request-ID")
    JSON_SORT_KEYS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN", "")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DOMAIN = os.getenv("REMEMBER_COOKIE_DOMAIN", SESSION_COOKIE_DOMAIN)
    REQUIRE_DB_AT_HEAD = False
    ENFORCE_STRICT_SECRETS = False

    UPLOAD_FOLDER = str(BASE_DIR / os.getenv("UPLOAD_FOLDER", "uploads"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 209715200))
    ALLOWED_EXTENSIONS = {"pdf"}
    DEFAULT_MINERU_URL = os.getenv("DEFAULT_MINERU_URL", "http://127.0.0.1:8000")


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    REQUIRE_DB_AT_HEAD = True
    ENFORCE_STRICT_SECRETS = True


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    REQUIRE_DB_AT_HEAD = False


CONFIG_MAP = {
    "dev": DevConfig,
    "prod": ProdConfig,
    "test": TestConfig,
}

