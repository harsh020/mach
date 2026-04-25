from __future__ import annotations

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_session": True,
    "idle_timeout_sec": None,
    "commit_closes_session": False,
    "auto_tracking": True,
    "hook_agents": ["claude", "codex", "copilot", "cursor", "gemini"],
    "poll_interval_sec": 2,
    "ignore_paths": [
        ".git",
        ".mach",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        "node_modules",
        "dist",
        "build",
    ],
}


def merge_config(raw_config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    merged.update(raw_config)
    return merged
