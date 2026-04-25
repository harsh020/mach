from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def current_branch(repo_root: Path) -> str | None:
    return _run_git(repo_root, "branch", "--show-current")


def head_commit(repo_root: Path) -> str | None:
    return _run_git(repo_root, "rev-parse", "HEAD")

