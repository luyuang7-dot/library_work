"""HTTP client for a locally running MinerU FastAPI service."""

from __future__ import annotations

import json

import requests


class MineruError(RuntimeError):
    """User-facing MinerU error."""


def _normalize_base_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if not value:
        raise MineruError("MinerU service URL is not configured.")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value


def health_check(base_url: str, timeout: float = 3.0) -> dict:
    base = _normalize_base_url(base_url)
    try:
        response = requests.get(f"{base}/health", timeout=timeout)
    except requests.RequestException as exc:
        raise MineruError(f"Cannot reach MinerU at {base}: {exc}") from exc

    if response.status_code != 200:
        raise MineruError(
            f"MinerU /health returned {response.status_code}: {response.text[:200]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise MineruError("MinerU /health did not return valid JSON.") from exc


def parse_pdf(
    base_url: str,
    file_bytes: bytes,
    filename: str,
    *,
    backend: str = "pipeline",
    lang: str = "ch",
    timeout: float = 3600.0,
) -> dict:
    base = _normalize_base_url(base_url)
    files = {"files": (filename or "upload.pdf", file_bytes, "application/pdf")}
    data = {
        "backend": backend,
        "lang_list": lang,
        "parse_method": "auto",
        "formula_enable": "false",
        "table_enable": "false",
        "image_analysis": "false",
        "return_md": "true",
        "return_content_list": "true",
        "return_images": "false",
        "return_middle_json": "false",
        "return_model_output": "false",
        "response_format_zip": "false",
        "start_page_id": "0",
    }
    try:
        response = requests.post(
            f"{base}/file_parse",
            files=files,
            data=data,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise MineruError(f"MinerU request failed: {exc}") from exc

    if response.status_code != 200:
        raise MineruError(
            f"MinerU /file_parse returned {response.status_code}: {response.text[:1500]}"
        )

    payload = response.json()
    results = payload.get("results") or {}
    if not results:
        raise MineruError("MinerU returned an empty result payload.")

    _, first = next(iter(results.items()))
    markdown = first.get("md_content") or ""
    content_list_raw = first.get("content_list")
    content_list: list = []
    if content_list_raw:
        try:
            content_list = (
                json.loads(content_list_raw)
                if isinstance(content_list_raw, str)
                else content_list_raw
            )
        except json.JSONDecodeError:
            content_list = []

    return {"md": markdown, "content_list": content_list}
