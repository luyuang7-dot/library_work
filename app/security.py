import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

AI_AGENT_API_KEY_PREFIX = "enc:v1:"


def _coerce_secret(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError(
            "Missing AI agent encryption secret. Configure "
            "AI_AGENT_API_KEY_ENCRYPTION_KEY."
        )
    return text


def _resolve_ai_agent_secret() -> str:
    configured = current_app.config.get("AI_AGENT_API_KEY_ENCRYPTION_KEY")
    return _coerce_secret(configured)


def _build_fernet() -> Fernet:
    digest = hashlib.sha256(_resolve_ai_agent_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_ai_agent_api_key_encrypted(value: str | None) -> bool:
    return bool(value and value.startswith(AI_AGENT_API_KEY_PREFIX))


def encrypt_ai_agent_api_key(value: str | None) -> str | None:
    plain = (value or "").strip()
    if not plain:
        return None
    token = _build_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    return AI_AGENT_API_KEY_PREFIX + token


def decrypt_ai_agent_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if not is_ai_agent_api_key_encrypted(value):
        return value
    token = value[len(AI_AGENT_API_KEY_PREFIX) :]
    try:
        plain = _build_fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Invalid encrypted AI agent API key payload") from exc
    return plain.decode("utf-8")
