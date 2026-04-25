from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class MachPaths:
    repo_root: Path
    mach_dir: Path
    config_path: Path
    head_path: Path
    sessions_dir: Path
    db_path: Path
    pack_dir: Path
    lock_path: Path
    agent_sessions_path: Path
    inbox_dir: Path
    ingest_state_path: Path
    tracker_state_path: Path
    tracker_pid_path: Path
    tracker_log_path: Path
    tracker_lock_path: Path
