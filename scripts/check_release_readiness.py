from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_quality_checks as quality_checks
from scripts.create_release_record import RELEASE_RECORD_TEMPLATE


def _check(condition: bool, label: str, detail: str) -> str:
    status = "PASS" if condition else "FAIL"
    return f"[{status}] {label}: {detail}"


def build_report() -> str:
    lines: list[str] = []
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    deploy_script = (ROOT / "scripts" / "deploy_release.sh").read_text(
        encoding="utf-8"
    )
    rollback_script = (ROOT / "scripts" / "rollback_release.sh").read_text(
        encoding="utf-8"
    )
    quality_runner = (ROOT / "scripts" / "run_quality_checks.py").read_text(
        encoding="utf-8"
    )
    changelog_like_entry = re.search(
        rf"Version[:：]\s*{re.escape(version)}\b",
        readme,
        flags=re.IGNORECASE,
    )

    lines.append("# Release Readiness Check")
    lines.append("")
    lines.append(
        _check(
            bool(version) and version.count(".") == 2,
            "Version file",
            f"VERSION is set to {version or 'empty'}",
        )
    )
    lines.append(
        _check(
            bool(changelog_like_entry),
            "Changelog entry",
            "README includes the current version in its release/deploy guidance",
        )
    )
    lines.append(
        _check(
            "Pre-release Checks" in RELEASE_RECORD_TEMPLATE
            and "Post-release Verification" in RELEASE_RECORD_TEMPLATE
            and "Rollback Plan" in RELEASE_RECORD_TEMPLATE,
            "Release template",
            "embedded release record template includes checks, verification, and rollback",
        )
    )
    lines.append(
        _check(
            "scripts/post_release_smoke_test.sh" in RELEASE_RECORD_TEMPLATE
            and "scripts/collect_runtime_snapshot.sh" in RELEASE_RECORD_TEMPLATE
            and "Smoke test file / command output link" in RELEASE_RECORD_TEMPLATE,
            "Release evidence template",
            "embedded release template captures smoke-test and snapshot evidence",
        )
    )
    lines.append(
        _check(
            "scripts/finalize_release_record.sh" in readme
            and "python scripts/create_release_record.py" in readme
            and "scripts/deploy_release.sh" in readme
            and "scripts/rollback_release.sh" in readme
            and "scripts/capture_post_release_evidence.sh" in readme,
            "README release flow",
            "README documents the preferred and fallback release workflow",
        )
    )
    lines.append(
        _check(
            "Release Checklist" in readme
            and "Operational Notes" in readme
            and "artifacts/release_records/" in readme,
            "Release operations docs",
            "README consolidates release, evidence, and operational notes",
        )
    )
    lines.append(
        _check(
            'flask" --app wsgi:app init-db' in deploy_script
            and "/healthz" in deploy_script
            and "RUN_SMOKE_TEST" in deploy_script
            and "post_release_smoke_test.txt" in deploy_script
            and "runtime_snapshot_post_deploy.txt" in deploy_script
            and "/healthz" in rollback_script
            and "RUN_SMOKE_TEST" in rollback_script
            and "post_release_smoke_test_after_rollback.txt" in rollback_script
            and "runtime_snapshot_post_rollback.txt" in rollback_script,
            "Deploy / rollback scripts",
            "scripts include migration, health, smoke, and snapshot steps",
        )
    )
    lines.append(
        _check(
            "PYTEST_TARGETS" in quality_runner
            and "COVERAGE_FAIL_UNDER" in quality_runner
            and quality_checks.COVERAGE_FAIL_UNDER == "45",
            "Quality gate linkage",
            "release readiness is aligned with the local quality gate",
        )
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    print(build_report(), end="")


if __name__ == "__main__":
    main()
