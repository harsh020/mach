from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HookDispatchResult:
    handled: bool
    emitted_output: str = ""
    event: dict[str, Any] | None = None


class HookAdapter:
    name = "unknown"
    support = "unsupported"
    notes = ""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def install(self) -> dict[str, Any]:
        raise NotImplementedError

    def uninstall(self) -> dict[str, Any]:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    def dispatch(self, event_name: str, payload: dict[str, Any], repo_root: Path) -> HookDispatchResult:
        raise NotImplementedError

