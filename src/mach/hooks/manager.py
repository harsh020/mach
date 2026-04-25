from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mach.hooks.base import HookAdapter, HookDispatchResult
from mach.hooks.claude import ClaudeHookAdapter
from mach.hooks.codex import CodexHookAdapter
from mach.hooks.copilot import CopilotHookAdapter
from mach.hooks.cursor import CursorHookAdapter
from mach.hooks.gemini import GeminiHookAdapter
from mach.ingest import EventInboxService
from mach.session import MachError


class HookManager:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.ingest = EventInboxService(self.repo_root)
        self.adapters: dict[str, HookAdapter] = {
            "claude": ClaudeHookAdapter(self.repo_root),
            "codex": CodexHookAdapter(self.repo_root),
            "copilot": CopilotHookAdapter(self.repo_root),
            "cursor": CursorHookAdapter(self.repo_root),
            "gemini": GeminiHookAdapter(self.repo_root),
        }

    def install(self, agents: list[str] | None = None) -> dict[str, Any]:
        results = [self.adapters[name].install() for name in self._resolve_agents(agents)]
        return {"installed": results}

    def uninstall(self, agents: list[str] | None = None) -> dict[str, Any]:
        results = [self.adapters[name].uninstall() for name in self._resolve_agents(agents)]
        return {"uninstalled": results}

    def status(self, agents: list[str] | None = None) -> dict[str, Any]:
        return {"hooks": [self.adapters[name].status() for name in self._resolve_agents(agents)]}

    def installable_agents(self) -> list[str]:
        return [
            name
            for name, adapter in self.adapters.items()
            if adapter.support in {"full", "partial"}
        ]

    def available_agents(self) -> list[str]:
        return list(self.adapters.keys())

    def dispatch(self, agent: str, event_name: str, raw_payload: str, repo_root: Path | None = None) -> HookDispatchResult:
        adapter = self.adapters.get(agent)
        if not adapter:
            raise MachError(f"Unknown hook agent: {agent}")
        payload = json.loads(raw_payload) if raw_payload.strip() else {}
        result = adapter.dispatch(event_name, payload, (repo_root or self.repo_root).resolve())
        if result.event:
            self.ingest.submit_event(result.event)
        return result

    def _resolve_agents(self, agents: list[str] | None) -> list[str]:
        if not agents:
            return self.available_agents()
        resolved = []
        for agent in agents:
            if agent == "all":
                return self.available_agents()
            if agent == "installable":
                return self.installable_agents()
            if agent not in self.adapters:
                raise MachError(f"Unknown hook agent: {agent}")
            resolved.append(agent)
        return resolved
