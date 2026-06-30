from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_run_py_exits_outside_dev_mode(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "FLASK_ENV": "prod",
            "DATABASE_URL": f"sqlite:///{(tmp_path / 'runpy.sqlite').as_posix()}",
            "FLASK_SECRET_KEY": "test-secret-key",
            "AI_AGENT_API_KEY_ENCRYPTION_KEY": "test-ai-agent-encryption-key",
        }
    )

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "run.py"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert "run.py is for local development only" in combined
