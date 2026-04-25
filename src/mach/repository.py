from __future__ import annotations

from pathlib import Path

from mach.models import MachPaths


def resolve_paths(repo_root: Path | None = None) -> MachPaths:
    root = (repo_root or Path.cwd()).resolve()
    mach_dir = root / ".mach"
    return MachPaths(
        repo_root=root,
        mach_dir=mach_dir,
        config_path=mach_dir / "config",
        head_path=mach_dir / "HEAD",
        sessions_dir=mach_dir / "sessions",
        db_path=mach_dir / "index.db",
        pack_dir=mach_dir / "pack",
        lock_path=mach_dir / ".lock",
        agent_sessions_path=mach_dir / "agent_sessions.json",
        inbox_dir=mach_dir / "inbox",
        ingest_state_path=mach_dir / "ingest_state.json",
        tracker_state_path=mach_dir / "tracker_state.json",
        tracker_pid_path=mach_dir / "tracker.pid",
        tracker_log_path=mach_dir / "tracker.log",
        tracker_lock_path=mach_dir / ".tracker.lock",
    )
