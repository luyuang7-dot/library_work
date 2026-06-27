from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_quality_checks as quality_checks


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _check(condition: bool, label: str, detail: str) -> str:
    status = "PASS" if condition else "FAIL"
    return f"[{status}] {label}: {detail}"


def build_report() -> str:
    lines: list[str] = []

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ci_config = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    app_init = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")

    lines.append("# Hardening Status Verification")
    lines.append("")
    lines.append(
        _check(
            "REQUEST_ID_HEADER" in app_init and "request_complete" in app_init,
            "Request tracing",
            "request ID header and completion log wiring present in app init",
        )
    )
    lines.append(
        _check(
            "quality" in ci_config
            and "pip install -r requirements-dev.txt" in ci_config
            and "python scripts/run_quality_checks.py --skip-ruff --skip-pre-commit"
            in ci_config
            and "python scripts/verify_hardening_status.py" in ci_config
            and "tests/test_security_hardening.py" in quality_checks.PYTEST_TARGETS
            and "tests/test_verify_hardening_status.py"
            in quality_checks.PYTEST_TARGETS
            and quality_checks.COVERAGE_FAIL_UNDER == "45",
            "CI gate",
            "centralized quality gate includes regression checks and the coverage threshold",
        )
    )
    lines.append(
        _check(
            "install_runtime_stack.sh" in readme
            and "scripts/deploy_release.sh" in readme
            and "scripts/rollback_release.sh" in readme,
            "Runtime stack docs",
            "README documents the runtime install helper plus deploy and rollback scripts",
        )
    )
    lines.append(
        _check(
            "## Current Scope" in readme
            and "## SQL Usage" in readme
            and "## PDF Recognition" in readme,
            "Course scope docs",
            "README explains the retained scope, the SQL foundation, and the PDF workflow",
        )
    )

    pytest_result = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            *quality_checks.PYTEST_TARGETS,
            "-q",
        ]
    )
    pytest_ok = pytest_result.returncode == 0
    pytest_summary = (
        pytest_result.stdout.strip().splitlines()[-1]
        if pytest_result.stdout.strip()
        else f"returncode={pytest_result.returncode}"
    )
    lines.append(
        _check(
            pytest_ok,
            "Targeted regression suite",
            pytest_summary,
        )
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    print(build_report(), end="")


if __name__ == "__main__":
    main()
