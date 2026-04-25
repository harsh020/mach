from __future__ import annotations

from pathlib import Path
from typing import Any

from mach.session import SessionStore


def record_step(step_dict: dict[str, Any], repo_root: str | Path | None = None) -> dict[str, Any]:
    store = SessionStore(Path(repo_root).resolve() if repo_root else None)
    return store.record_step(step_dict)


def record_agent_step(
    agent: str,
    step_dict: dict[str, Any],
    repo_root: str | Path | None = None,
    source_session_id: str | None = None,
    task_desc: str | None = None,
    end_session: bool = False,
) -> dict[str, Any]:
    store = SessionStore(Path(repo_root).resolve() if repo_root else None)
    return store.record_agent_step(
        agent=agent,
        source_session_id=source_session_id,
        task_desc=task_desc,
        step_dict=step_dict,
        end_session=end_session,
    )
