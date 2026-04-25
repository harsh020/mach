from __future__ import annotations

from pathlib import Path

from mach.hooks.base import HookAdapter, HookDispatchResult


class CursorHookAdapter(HookAdapter):
    name = "cursor"
    support = "status-webhook-only"
    notes = "Cursor exposes background-agent status webhooks and MCP, but not a full prompt/tool hook surface."

    def install(self) -> dict[str, object]:
        return {"agent": self.name, "installed": False, "support": self.support, "notes": self.notes}

    def uninstall(self) -> dict[str, object]:
        return {"agent": self.name, "installed": False, "support": self.support, "notes": self.notes}

    def status(self) -> dict[str, object]:
        return {"agent": self.name, "configured": False, "support": self.support, "notes": self.notes}

    def dispatch(self, event_name: str, payload: dict[str, object], repo_root: Path) -> HookDispatchResult:
        del event_name, payload, repo_root
        return HookDispatchResult(handled=False)

