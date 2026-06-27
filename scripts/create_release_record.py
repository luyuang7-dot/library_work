from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
TEMPLATE_FILE = ROOT / "scripts" / "release_log_template.md"
OUTPUT_DIR = ROOT / "artifacts" / "release_records"
DEFAULT_SMOKE_FILENAME = "post_release_smoke_test.txt"
DEFAULT_SNAPSHOT_FILENAME = "runtime_snapshot.txt"
RELEASE_RECORD_TEMPLATE = """
## Change Summary

- 

## Pre-release Checks

- [ ] `python scripts/check_release_readiness.py`
- [ ] `python scripts/run_quality_checks.py --skip-ruff --skip-pre-commit`

## Deployment Steps

- [ ] `scripts/deploy_release.sh` executed
- [ ] `scripts/post_release_smoke_test.sh` captured
- [ ] `scripts/collect_runtime_snapshot.sh` captured

## Post-release Verification

- [ ] `/healthz` returned success
- [ ] Login, document list, batch PDF recognition, and BibTeX workflow checked
- [ ] Background timers and request logging verified

## Monitoring Trace

- Health check request ID:
- Smoke test file / command output link:
- Snapshot file / command output link:
- Scheduled health probe log excerpt:
- Alert log excerpt (`journalctl -t personal_library_alert`):
- Related issue / feedback links:

## Rollback Plan

- [ ] `scripts/rollback_release.sh <previous-version>` prepared if needed
- [ ] Rollback impact and operator notes recorded
""".strip()


def _load_template_text() -> str:
    if TEMPLATE_FILE.exists():
        value = TEMPLATE_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    return RELEASE_RECORD_TEMPLATE


def _default_version() -> str:
    if VERSION_FILE.exists():
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    return "0.0.0"


def _git_short_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _display_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_optional_file(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _resolve_evidence_dir(
    evidence_dir: str | None,
    smoke_file: str | None,
    snapshot_file: str | None,
) -> tuple[Path | None, Path | None]:
    smoke_path = _resolve_optional_file(smoke_file)
    snapshot_path = _resolve_optional_file(snapshot_file)

    if not evidence_dir:
        return smoke_path, snapshot_path

    base = _resolve_optional_file(evidence_dir)
    if base is None:
        return smoke_path, snapshot_path
    if smoke_path is None:
        candidate = base / DEFAULT_SMOKE_FILENAME
        if candidate.exists():
            smoke_path = candidate
    if snapshot_path is None:
        candidate = base / DEFAULT_SNAPSHOT_FILENAME
        if candidate.exists():
            snapshot_path = candidate
    return smoke_path, snapshot_path


def _extract_request_id(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("request_id="):
            return line.partition("=")[2].strip()
    return ""


def _mark_checkbox(text: str, label: str, checked: bool) -> str:
    marker = "[x]" if checked else "[ ]"
    return text.replace(f"- [ ] {label}", f"- {marker} {label}")


def _fill_line(text: str, prefix: str, value: str) -> str:
    if not value:
        return text
    return text.replace(prefix, f"{prefix} {value}")


def _build_record(
    version: str,
    environment: str,
    operator: str,
    commit_ref: str,
    *,
    health_request_id: str = "",
    smoke_file: Path | None = None,
    snapshot_file: Path | None = None,
    scheduled_health_log: str = "",
    alert_log_ref: str = "",
    related_links: str = "",
) -> str:
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    template = _load_template_text()
    template = _mark_checkbox(
        template,
        "`scripts/post_release_smoke_test.sh` captured",
        smoke_file is not None,
    )
    template = _mark_checkbox(
        template,
        "`scripts/collect_runtime_snapshot.sh` captured",
        snapshot_file is not None,
    )
    template = _fill_line(template, "- Health check request ID:", health_request_id)
    template = _fill_line(
        template,
        "- Smoke test file / command output link:",
        _display_path(smoke_file),
    )
    template = _fill_line(
        template,
        "- Snapshot file / command output link:",
        _display_path(snapshot_file),
    )
    template = _fill_line(
        template,
        "- Scheduled health probe log excerpt:",
        scheduled_health_log,
    )
    template = _fill_line(
        template,
        "- Alert log excerpt (`journalctl -t personal_library_alert`):",
        alert_log_ref,
    )
    template = _fill_line(
        template,
        "- Related issue / feedback links:",
        related_links,
    )
    header = "\n".join(
        [
            "# Release Record",
            "",
            f"- Version: {version}",
            f"- Date: {created_at}",
            f"- Operator: {operator}",
            f"- Commit / tag: {commit_ref}",
            f"- Environment: {environment}",
            "",
            "<!-- Generated by scripts/create_release_record.py -->",
            "",
        ]
    )
    _, _, remainder = template.partition("## Change Summary")
    return header + "## Change Summary" + remainder + "\n"


def create_release_record(
    version: str,
    environment: str,
    operator: str,
    commit_ref: str,
    *,
    health_request_id: str = "",
    smoke_file: str | None = None,
    snapshot_file: str | None = None,
    evidence_dir: str | None = None,
    scheduled_health_log: str = "",
    alert_log_ref: str = "",
    related_links: str = "",
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    resolved_smoke, resolved_snapshot = _resolve_evidence_dir(
        evidence_dir,
        smoke_file,
        snapshot_file,
    )
    resolved_request_id = health_request_id or _extract_request_id(
        resolved_snapshot
    ) or _extract_request_id(resolved_smoke)
    output_path = OUTPUT_DIR / f"{version}-{environment}.md"
    output_path.write_text(
        _build_record(
            version,
            environment,
            operator,
            commit_ref,
            health_request_id=resolved_request_id,
            smoke_file=resolved_smoke,
            snapshot_file=resolved_snapshot,
            scheduled_health_log=scheduled_health_log,
            alert_log_ref=alert_log_ref,
            related_links=related_links,
        ),
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a release record from the repository template."
    )
    parser.add_argument("--version", default=_default_version())
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--operator", default="TODO")
    parser.add_argument("--commit-ref", default=_git_short_head())
    parser.add_argument("--health-request-id", default="")
    parser.add_argument("--smoke-file", default=None)
    parser.add_argument("--snapshot-file", default=None)
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--scheduled-health-log", default="")
    parser.add_argument("--alert-log-ref", default="")
    parser.add_argument("--related-links", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = create_release_record(
        version=args.version,
        environment=args.environment,
        operator=args.operator,
        commit_ref=args.commit_ref,
        health_request_id=args.health_request_id,
        smoke_file=args.smoke_file,
        snapshot_file=args.snapshot_file,
        evidence_dir=args.evidence_dir,
        scheduled_health_log=args.scheduled_health_log,
        alert_log_ref=args.alert_log_ref,
        related_links=args.related_links,
    )
    print(output_path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
