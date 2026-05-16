from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return {}


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")


def strip_matching_commands(hooks: dict[str, Any], needle: str) -> dict[str, Any]:
    result = dict(hooks)
    hook_map = dict(result.get("hooks", {}))
    cleaned: dict[str, Any] = {}

    for event_name, entries in hook_map.items():
        kept = []
        for entry in entries:
            hook_list = []
            for hook in entry.get("hooks", []):
                command = str(hook.get("command", ""))
                bash = str(hook.get("bash", ""))
                powershell = str(hook.get("powershell", ""))
                if needle in command or needle in bash or needle in powershell:
                    continue
                hook_list.append(hook)
            if hook_list:
                kept.append({**entry, "hooks": hook_list})
        if kept:
            cleaned[event_name] = kept

    result["hooks"] = cleaned
    return result


def merge_event_hooks(hooks: dict[str, Any], additions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    merged = dict(hooks)
    hook_map = dict(merged.get("hooks", {}))
    for event_name, entries in additions.items():
        existing = list(hook_map.get(event_name, []))
        existing.extend(entries)
        hook_map[event_name] = existing
    merged["hooks"] = hook_map
    return merged


def command_name() -> str:
    return os.environ.get("MACH_HOOKS_BIN", "mach")


def first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def nested_first_present(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = payload
        ok = True
        for key in path:
            if not isinstance(value, dict) or key not in value:
                ok = False
                break
            value = value[key]
        if ok and value is not None:
            return value
    return None


def latest_user_message(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") in {"text", "input_text"}:
                        text = item.get("text")
                        if text:
                            text_parts.append(str(text))
                if text_parts:
                    return "\n".join(text_parts)
            # Gemini CLI format: message has 'parts' list of {text: ...} dicts
            parts = message.get("parts")
            if isinstance(parts, list):
                text_parts = []
                for item in parts:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text:
                            text_parts.append(str(text))
                if text_parts:
                    return "\n".join(text_parts)
    return None

def extract_tool_details(repo_root: Path, tool_name: str, tool_input: Any) -> tuple[str, list[dict[str, Any]]]:
    name_lower = str(tool_name).lower()
    category = "exec"
    if any(x in name_lower for x in ["write", "replace", "edit", "create", "multi_replace"]):
        category = "write"
    elif any(x in name_lower for x in ["read", "view", "cat", "grep"]):
        category = "read"
    elif any(x in name_lower for x in ["list", "search", "find"]):
        category = "search"
        
    file_changes = []
    parsed = None
    if isinstance(tool_input, dict):
        parsed = tool_input
    elif isinstance(tool_input, str):
        try:
            import ast
            parsed = ast.literal_eval(tool_input)
        except Exception:
            try:
                import json
                parsed = json.loads(tool_input)
            except Exception:
                pass
                
    if isinstance(parsed, dict):
        path = first_present(parsed, "file_path", "path", "TargetFile", "AbsolutePath", "file", "SearchPath", "DirectoryPath")
        if path:
            action = "read"
            if category == "write":
                action = "write"
                
            abs_path = Path(path)
            if not abs_path.is_absolute():
                abs_path = (repo_root / path).resolve()
                
            change: dict[str, Any] = {
                "file_path": str(abs_path),
                "action": action,
            }
            
            hunks = []
            lines_added = 0
            lines_removed = 0
            
            start = first_present(parsed, "StartLine", "start_line", "startLine", "start")
            end = first_present(parsed, "EndLine", "end_line", "endLine", "end")
            
            if start is not None and end is not None:
                try:
                    s, e = int(start), int(end)
                    hunks.append({"from": s, "to": e})
                    lines_removed += (e - s + 1)
                except Exception:
                    pass
                    
            chunks = first_present(parsed, "ReplacementChunks", "chunks", "replacements")
            if isinstance(chunks, list):
                for chunk in chunks:
                    if isinstance(chunk, dict):
                        cs = first_present(chunk, "StartLine", "start")
                        ce = first_present(chunk, "EndLine", "end")
                        rc = first_present(chunk, "ReplacementContent", "content")
                        if cs is not None and ce is not None:
                            try:
                                hunks.append({"from": int(cs), "to": int(ce)})
                                lines_removed += (int(ce) - int(cs) + 1)
                            except Exception:
                                pass
                        if rc and isinstance(rc, str):
                            lines_added += len(rc.splitlines())
                            
            content = first_present(parsed, "CodeContent", "ReplacementContent", "content")
            if content and isinstance(content, str):
                lines_added += len(content.splitlines())
                
            if hunks:
                change["hunks"] = hunks
            if action == "write":
                change["lines_added"] = lines_added
                change["lines_removed"] = lines_removed
                
            if abs_path.exists():
                try:
                    import subprocess
                    out = subprocess.check_output(["git", "hash-object", str(abs_path)], cwd=str(repo_root), stderr=subprocess.DEVNULL)
                    change["before_blob"] = out.decode("utf-8").strip()
                except Exception:
                    pass
                    
            file_changes.append(change)
            
    return category, file_changes

