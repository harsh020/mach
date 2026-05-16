from __future__ import annotations

from pathlib import Path
from typing import Any

from mach.hooks.base import HookAdapter, HookDispatchResult
from mach.hooks.helpers import command_name, first_present, merge_event_hooks, read_json_file, write_json_file, extract_tool_details


class CopilotHookAdapter(HookAdapter):
    name = "copilot"
    support = "full"
    notes = "GitHub Copilot coding agent and CLI support repository hooks in .github/hooks/*.json."

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)
        self.path = repo_root / ".github" / "hooks" / "mach.json"

    def install(self) -> dict[str, Any]:
        command = command_name()
        payload = {
            "version": 1,
            "hooks": {
                "sessionStart": [self._command(f'{command} hooks dispatch --agent copilot --event sessionStart')],
                "sessionEnd": [self._command(f'{command} hooks dispatch --agent copilot --event sessionEnd')],
                "userPromptSubmitted": [self._command(f'{command} hooks dispatch --agent copilot --event userPromptSubmitted')],
                "preToolUse": [self._command(f'{command} hooks dispatch --agent copilot --event preToolUse')],
                "postToolUse": [self._command(f'{command} hooks dispatch --agent copilot --event postToolUse')],
                "agentStop": [self._command(f'{command} hooks dispatch --agent copilot --event agentStop')],
                "subagentStop": [self._command(f'{command} hooks dispatch --agent copilot --event subagentStop')],
                "errorOccurred": [self._command(f'{command} hooks dispatch --agent copilot --event errorOccurred')],
            },
        }
        write_json_file(self.path, payload)
        return {"agent": self.name, "installed": True, "path": str(self.path), "support": self.support}

    def uninstall(self) -> dict[str, Any]:
        if self.path.exists():
            self.path.unlink()
        return {"agent": self.name, "installed": False, "path": str(self.path), "support": self.support}

    def status(self) -> dict[str, Any]:
        hooks = read_json_file(self.path)
        return {
            "agent": self.name,
            "support": self.support,
            "configured": bool(hooks.get("hooks")) if hooks else False,
            "path": str(self.path),
            "notes": self.notes,
        }

    def dispatch(self, event_name: str, payload: dict[str, Any], repo_root: Path) -> HookDispatchResult:
        session_id = first_present(payload, "sessionId", "session_id")
        if event_name == "sessionEnd":
            return HookDispatchResult(handled=True, event={"kind": "session_end", "agent": self.name, "source_session_id": session_id})
        if event_name == "sessionStart":
            return self._step(session_id, "reasoning", "Copilot session started")
        if event_name == "userPromptSubmitted":
            prompt = first_present(payload, "prompt", "userPrompt")
            return self._step(session_id, "input", str(prompt or ""))
        if event_name in {"preToolUse", "postToolUse"}:
            tool_name = str(first_present(payload, "toolName", "tool_name") or "unknown")
            tool_input = first_present(payload, "toolInput", "tool_input", "arguments")
            tool_output = first_present(payload, "toolOutput", "tool_output", "result", "error")
            
            category, file_changes = extract_tool_details(self.repo_root, tool_name, tool_input)
            
            step: dict[str, Any] = {
                "type": "tool",
                "content": f"{event_name}: {tool_name}",
                "tool": {
                    "name": tool_name,
                    "category": category,
                    "content": str(tool_input or ""),
                },
            }
            if file_changes:
                step["file_changes"] = file_changes
            if tool_output is not None:
                step["tool_result"] = tool_output
            return HookDispatchResult(
                handled=True,
                event={"kind": "step", "agent": self.name, "source_session_id": session_id, "step": step},
            )
        if event_name in {"agentStop", "subagentStop"}:
            output = first_present(payload, "message", "response", "summary") or event_name
            return self._step(session_id, "output", str(output))
        if event_name == "errorOccurred":
            error = first_present(payload, "error", "message") or "Copilot error"
            return self._step(session_id, "output", str(error))
        return HookDispatchResult(handled=False)

    @staticmethod
    def _command(bash: str) -> dict[str, Any]:
        return {"type": "command", "bash": bash, "cwd": ".", "timeoutSec": 30}

    def _step(self, session_id: Any, step_type: str, content: str) -> HookDispatchResult:
        return HookDispatchResult(
            handled=True,
            event={
                "kind": "step",
                "agent": self.name,
                "source_session_id": str(session_id) if session_id else None,
                "step": {"type": step_type, "content": content},
            },
        )

