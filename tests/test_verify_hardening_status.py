from __future__ import annotations

import scripts.verify_hardening_status as verify_status


def test_build_report_mentions_core_sections(monkeypatch):
    def fake_run(_command):
        class Result:
            returncode = 0
            stdout = "........\n8 passed in 1.23s\n"

        return Result()

    monkeypatch.setattr(verify_status, "_run", fake_run)

    report = verify_status.build_report()

    assert "# Hardening Status Verification" in report
    assert "[PASS] Request tracing" in report
    assert "[PASS] CI gate" in report
    assert "[PASS] Runtime stack docs" in report
    assert "[PASS] Course scope docs" in report
    assert "[PASS] Targeted regression suite: 8 passed in 1.23s" in report
