from __future__ import annotations

import scripts.check_release_readiness as release_readiness


def test_release_readiness_report_mentions_core_sections():
    report = release_readiness.build_report()

    assert "# Release Readiness Check" in report
    assert "[PASS] Version file" in report
    assert "[PASS] Changelog entry" in report
    assert "[PASS] Release template" in report
    assert "[PASS] Release evidence template" in report
    assert "[PASS] README release flow" in report
    assert "[PASS] Release operations docs" in report
    assert "[PASS] Deploy / rollback scripts" in report
    assert "[PASS] Quality gate linkage" in report
