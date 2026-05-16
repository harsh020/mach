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

def remote_origin_url(repo_root: Path) -> str | None:
    return _run_git(repo_root, "config", "--get", "remote.origin.url")

def repository_name(repo_root: Path) -> str:
    url = remote_origin_url(repo_root)
    if url:
        base = url.split("/")[-1]
        if base.endswith(".git"):
            base = base[:-4]
        return base
    return repo_root.name


def default_branch(repo_root: Path) -> str:
    """Best-effort detection of the default branch name."""
    # Try symbolic-ref of origin/HEAD first
    ref = _run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD", "--short")
    if ref:
        # returns e.g. "origin/main" → strip the remote prefix
        return ref.split("/", 1)[-1]
    # Fallback: check if 'main' branch exists, otherwise 'master'
    branches = _run_git(repo_root, "branch", "--list", "main")
    if branches:
        return "main"
    return "master"


def detect_provider(remote_url: str | None) -> str:
    """Infer the git hosting provider from the remote URL."""
    if not remote_url:
        return "unknown"
    url_lower = remote_url.lower()
    if "github.com" in url_lower:
        return "github"
    if "gitlab.com" in url_lower or "gitlab" in url_lower:
        return "gitlab"
    if "bitbucket.org" in url_lower or "bitbucket" in url_lower:
        return "bitbucket"
    if "azure.com" in url_lower or "dev.azure" in url_lower:
        return "azure"
    return "other"

