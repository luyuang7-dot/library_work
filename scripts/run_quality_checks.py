from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_COMPILE_TARGETS = [
    "app/__init__.py",
    "app/blueprints/auth.py",
    "app/blueprints/documents.py",
    "app/blueprints/batch_bibtex.py",
    "app/blueprints/settings.py",
    "app/services/file_io.py",
    "app/services/mineru_client.py",
    "app/services/schema_bootstrap.py",
    "scripts/check_release_readiness.py",
    "scripts/create_release_record.py",
    "scripts/package_production_release.py",
    "scripts/verify_hardening_status.py",
    "config.py",
    "run.py",
    "wsgi.py",
]
SHELL_SCRIPT_TARGETS = [
    "scripts/deploy_release.sh",
    "scripts/rollback_release.sh",
    "scripts/post_release_smoke_test.sh",
    "scripts/capture_post_release_evidence.sh",
    "scripts/finalize_release_record.sh",
    "scripts/collect_runtime_snapshot.sh",
    "scripts/check_runtime_health.sh",
    "scripts/emit_runtime_alert.sh",
    "scripts/install_runtime_stack.sh",
]
PYTEST_TARGETS = [
    "tests/test_ai_agent.py",
    "tests/test_app_init.py",
    "tests/test_batch_bibtex.py",
    "tests/test_bibtex_io.py",
    "tests/test_config_version.py",
    "tests/test_dict_cleanup_tags.py",
    "tests/test_document_barcode.py",
    "tests/test_documents_pagination.py",
    "tests/test_file_io.py",
    "tests/test_models.py",
    "tests/test_release_readiness.py",
    "tests/test_release_record_generator.py",
    "tests/test_routes.py",
    "tests/test_run_py.py",
    "tests/test_schema_bootstrap.py",
    "tests/test_security_hardening.py",
    "tests/test_verify_hardening_status.py",
]
COVERAGE_FAIL_UNDER = "45"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _find_runnable_bash() -> str | None:
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        result = subprocess.run(
            [bash, "-lc", "true"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    return bash if result.returncode == 0 else None


def run_quality_checks(*, skip_ruff: bool, skip_pre_commit: bool) -> None:
    _run([sys.executable, "-m", "py_compile", *PY_COMPILE_TARGETS])

    bash = _find_runnable_bash()
    if bash:
        for script_path in SHELL_SCRIPT_TARGETS:
            _run([bash, "-n", script_path])
    else:
        print(
            "bash not installed locally or not runnable here; "
            "skipping shell syntax check."
        )

    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            *PYTEST_TARGETS,
            "--cov=app",
            "--cov-report=term-missing",
            f"--cov-fail-under={COVERAGE_FAIL_UNDER}",
        ]
    )

    if skip_ruff:
        print("Skipping ruff check.")
    elif shutil.which("ruff"):
        _run(["ruff", "check", "."])
    else:
        print("ruff not installed locally; skipping lint.")

    if skip_pre_commit:
        print("Skipping pre-commit hooks.")
    elif shutil.which("pre-commit"):
        _run(["pre-commit", "run", "--all-files"])
    else:
        print("pre-commit not installed locally; skipping hooks.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the repository's local quality gate."
    )
    parser.add_argument("--skip-ruff", action="store_true")
    parser.add_argument("--skip-pre-commit", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_quality_checks(
        skip_ruff=args.skip_ruff,
        skip_pre_commit=args.skip_pre_commit,
    )


if __name__ == "__main__":
    main()
