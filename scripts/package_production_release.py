from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
VERSION_FILE = ROOT / "VERSION"

PACKAGE_PATHS = [
    "app",
    "deploy",
    "migrations",
    "scripts",
    "requirements.txt",
    ".env.example",
    "alembic.ini",
    "config.py",
    "run.py",
    "wsgi.py",
    "VERSION",
    "README.md",
    "LICENSE",
]

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
EXCLUDED_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _default_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def _add_path(tar: tarfile.TarFile, path: Path, release_root: str) -> None:
    arcname = Path(release_root) / path.relative_to(ROOT)
    tar.add(
        path,
        arcname=arcname.as_posix(),
        recursive=True,
        filter=_tar_filter,
    )


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    path = Path(tarinfo.name)
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
        return None
    if any(path.name.endswith(suffix) for suffix in EXCLUDED_FILE_SUFFIXES):
        return None
    return tarinfo


def package_release(*, version: str, archive_path: Path) -> dict[str, Any]:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    release_root = f"personal_library-{version}"
    with tarfile.open(archive_path, "w:gz") as tar:
        for rel in PACKAGE_PATHS:
            path = ROOT / rel
            if not path.exists():
                raise FileNotFoundError(f"required package path missing: {path}")
            _add_path(tar, path, release_root)

    summary = {
        "version": version,
        "archive_path": str(archive_path),
        "release_root": release_root,
        "included_paths": PACKAGE_PATHS,
        "archive_size_bytes": archive_path.stat().st_size,
    }
    summary_path = archive_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a minimal production release archive."
    )
    parser.add_argument("--version", default=_default_version())
    parser.add_argument(
        "--archive-path",
        default="",
        help="Output .tar.gz path. Defaults to artifacts/personal_library-<version>.tar.gz",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    archive_path = (
        Path(args.archive_path)
        if args.archive_path
        else ARTIFACTS_DIR / f"personal_library-{args.version}.tar.gz"
    )
    summary = package_release(
        version=args.version,
        archive_path=archive_path,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
