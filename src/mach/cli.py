from __future__ import annotations

import argparse
import json
import sys
import pydoc
import termios
import tty
import getpass
import urllib.request
import urllib.error
import time
from pathlib import Path

from mach.auth import save_token, logout, get_token

from mach.hooks import HookManager
from mach.ingest import EventInboxService
from mach.session import MachError, SessionStore
from mach.tracker import TrackerService

from mach.ui import render_sessions_list, render_session_steps, render_session_details

# Backward-compatible aliases used by log_command / show_command
def format_sessions_list(sessions: list[dict]) -> str:
    return render_sessions_list(sessions)

def format_session_steps(data: dict, oneline: bool = False, patch: bool = False) -> str:
    return render_session_steps(data, oneline=oneline, patch=patch)

def format_session_details(data: dict, patch: bool = False) -> str:
    return render_session_details(data, patch=patch)
def emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _select_from_terminal(
    prompt: str,
    choices: list[dict[str, str]],
    selected_values: list[str],
) -> list[str]:
    if not choices:
        return []

    selected = set(selected_values)
    cursor = 0
    line_count = len(choices) + 3
    rendered = False

    def render() -> None:
        nonlocal rendered
        if rendered:
            sys.stderr.write(f"\x1b[{line_count}F")
        sys.stderr.write(f"\x1b[2K\r{prompt}\n")
        sys.stderr.write("\x1b[2K\rUse Up/Down to move, Space to select, Enter when done.\n")
        sys.stderr.write("\x1b[2K\r\n")
        for index, choice in enumerate(choices):
            pointer = ">" if index == cursor else " "
            mark = "[x]" if choice["value"] in selected else "[ ]"
            sys.stderr.write(f"\x1b[2K\r{pointer} {mark} {choice['label']}\n")
        sys.stderr.flush()
        rendered = True

    def read_key() -> str:
        char = sys.stdin.read(1)
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x1b":
            suffix = sys.stdin.read(2)
            if suffix == "[A":
                return "up"
            if suffix == "[B":
                return "down"
            return "escape"
        if char in {"\r", "\n"}:
            return "enter"
        if char == " ":
            return "space"
        return char

    old_settings = termios.tcgetattr(sys.stdin)
    sys.stderr.write("\x1b[?25l")
    try:
        tty.setraw(sys.stdin.fileno())
        render()
        while True:
            key = read_key()
            if key == "up":
                cursor = (cursor - 1) % len(choices)
            elif key == "down":
                cursor = (cursor + 1) % len(choices)
            elif key == "space":
                value = choices[cursor]["value"]
                if value in selected:
                    selected.remove(value)
                else:
                    selected.add(value)
            elif key == "enter":
                break
            render()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        sys.stderr.write("\x1b[?25h")
        sys.stderr.flush()

    sys.stderr.write("\n")
    sys.stderr.flush()
    return [choice["value"] for choice in choices if choice["value"] in selected]


def _choose_hook_agents(manager: HookManager, requested_agents: str | None = None) -> list[str]:
    if requested_agents is not None:
        return [agent for agent in requested_agents.split(",") if agent]

    default_agents = manager.available_agents()
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return default_agents

    choices = [
        {
            "value": name,
            "label": f"{name} ({manager.adapters[name].support})",
        }
        for name in manager.available_agents()
    ]
    return _select_from_terminal("Select agent hooks to install:", choices, default_agents)


def init_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    mach_dir = store.init_repo()
    manager = HookManager()
    hook_agents = _choose_hook_agents(manager, args.hook_agents)
    config = store.update_config({"enabled": True, "hook_agents": hook_agents})
    hook_results = manager.install(hook_agents) if hook_agents else {"installed": []}
    tracker = TrackerService()
    tracker.ensure_state()
    tracking = tracker.start_daemon() if config.get("auto_tracking", True) else tracker.status()
    print(f"Success: Mach initialized in {mach_dir}")


def enable_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    config = store.update_config({"enabled": True})
    manager = HookManager()
    hook_results = manager.install(config.get("hook_agents") or manager.installable_agents())
    tracker = TrackerService()
    tracking = tracker.start_daemon() if config.get("auto_tracking", True) else tracker.status()
    print("Success: Mach tracking enabled.")


def disable_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    config = store.update_config({"enabled": False})
    hook_results = HookManager().uninstall(config.get("hook_agents"))
    tracking = TrackerService().stop_daemon()
    print("Success: Mach tracking disabled.")


def login_command(args: argparse.Namespace) -> None:
    token = args.token
    if not token:
        token = getpass.getpass("Enter your Mach Personal Access Token: ").strip()
    
    if not token:
        print("Error: Token cannot be empty.", file=sys.stderr)
        sys.exit(1)

    save_token(token)
    print("Success: Logged in. Token saved globally to ~/.mach/credentials.json")


def logout_command(_: argparse.Namespace) -> None:
    logout()
    print("Success: Logged out.")


def push_command(args: argparse.Namespace) -> None:
    token = get_token()
    if not token:
        print("Error: You must log in first. Run: mach login", file=sys.stderr)
        sys.exit(1)

    session_id = args.session_id

    # Handle --reset or --reset-to: clear or rewind the local push tracking
    if getattr(args, "reset", False) or getattr(args, "reset_to", None):
        _push_reset(session_id, reset_to=getattr(args, "reset_to", None))
        return

    print(f"Pushing session {session_id} to Mach Web...")
    
    store = SessionStore()
    try:
        from mach import __version__
        from mach.git_utils import current_branch, remote_origin_url, repository_name
        from mach.models import PushMerkle, PushMetadata, PushPayload, PushResponse, PushSessionMeta

        meta = store.read_session_meta(session_id)
        remote = meta.get("remote", {})
        remote_url = remote.get("url") or remote_origin_url(store.paths.repo_root)
        repo_name = remote.get("repository_name") or repository_name(store.paths.repo_root)
        print(f"  Repository: {repo_name}")
        print("  Calculating Merkle deltas...")
        
        # Determine what needs to be pushed
        last_pushed_id = remote.get("last_pushed_step_id")
        session_dir = store.paths.sessions_dir / session_id
        steps_file = session_dir / "steps.jsonl"
        
        all_steps = []
        if steps_file.exists():
            with open(steps_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            for line in lines:
                if not line.strip(): continue
                step_data = json.loads(line)
                all_steps.append(step_data)
        
        steps_to_push = all_steps
        if last_pushed_id:
            for index, step_data in enumerate(all_steps):
                if step_data.get("id") == last_pushed_id:
                    steps_to_push = all_steps[index + 1:]
                    break
        
        if not steps_to_push:
            print(f"Success: Session {session_id} is already up-to-date.")
            return
            
        total_steps = len(steps_to_push)
        print(f"  Found {total_steps} unpushed steps. Uploading...")

        # Read merkle root for client_root
        merkle_path = session_dir / "merkle.sig"
        merkle = {}
        if merkle_path.exists():
            with open(merkle_path, "r", encoding="utf-8") as f:
                merkle = json.load(f)

        risk_count = sum(len(step.get("risk_flags", [])) for step in all_steps)

        config = store.read_config()
        base_url = config.get("api_base_url", "http://localhost:8000").rstrip("/")
        endpoint = f"{base_url}/api/v1/sessions/sync/"

        BATCH_SIZE = 50
        pushed_count = 0

        for batch_start in range(0, total_steps, BATCH_SIZE):
            batch = steps_to_push[batch_start:batch_start + BATCH_SIZE]

            blobs: dict[str, str] = {}
            formatted_steps = []
            for step in batch:
                formatted_steps.append(_format_push_step(store, step, blobs))

            payload_obj = PushPayload(
                repository=remote_url or repo_name,
                meta=PushSessionMeta(
                    id=session_id,
                    agent=meta.get("agent", "unknown"),
                    agent_session_id=meta.get("agent_session_id"),
                    task_desc=meta.get("task_desc"),
                    started_at=meta.get("started_at", 0),
                    ended_at=meta.get("ended_at"),
                    status=meta.get("status", "active"),
                    branch=meta.get("branch") or current_branch(store.paths.repo_root) or "unknown",
                    pre_commit=meta.get("pre_commit"),
                    post_commit=meta.get("post_commit"),
                    step_count=len(all_steps),
                    risk_count=risk_count,
                ),
                merkle=PushMerkle(
                    root=merkle.get("root"),
                    steps=int(merkle.get("steps") or len(all_steps)),
                ),
                blobs=blobs,
                steps=formatted_steps,
                client_root=merkle.get("root"),
                metadata=PushMetadata(
                    cli_version=__version__,
                    pushed_from=_push_host_name(),
                ),
            )
            payload = payload_obj.to_dict()

            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(req) as response:
                    if response.status not in (200, 201):
                        print(f"\nError: Backend returned status {response.status}", file=sys.stderr)
                        sys.exit(1)

                    resp_body = response.read().decode("utf-8")
                    push_response = PushResponse.from_dict(json.loads(resp_body) if resp_body else {})
            except urllib.error.HTTPError as http_err:
                body = http_err.read().decode("utf-8", errors="replace")
                print(f"\nError: Backend returned status {http_err.code}", file=sys.stderr)
                if body:
                    print(body, file=sys.stderr)
                sys.exit(1)
            except urllib.error.URLError as req_err:
                print(f"\nError: Could not connect to backend ({endpoint}): {req_err}", file=sys.stderr)
                sys.exit(1)

            # Update local tracking after each successful batch (resumable on failure)
            pushed_count += len(batch)
            percent = int((pushed_count / total_steps) * 100)
            sys.stdout.write(f"\r  Uploading: {percent:3d}% ({pushed_count}/{total_steps})")
            sys.stdout.flush()

            pushed_root = push_response.server_root_after or push_response.session.merkle_root or push_response.client_root
            pushed_at = push_response.created or push_response.session.synced_at
            store.update_push_state(
                session_id,
                remote_updates={
                    "url": remote_url,
                    "repository_name": repo_name,
                    "last_push_id": push_response.id,
                    "last_pushed_at": pushed_at,
                    "last_pushed_ts": int(time.time()),
                    "last_pushed_step_id": batch[-1].get("id"),
                    "pushed_root": pushed_root,
                    "server_session_id": push_response.session.id,
                    "server_root_before": push_response.server_root_before,
                    "server_root_after": push_response.server_root_after,
                    "blobs_received": push_response.blobs_received,
                    "steps_received": push_response.steps_received,
                },
                step_count=push_response.session.step_count,
                risk_count=push_response.session.risk_count,
            )

        print(f"\nSuccess: Synced session {session_id} to backend.")
        print(f"  Push ID: {push_response.id or 'unknown'}")
        print(f"  Steps sent: {pushed_count}; batches: {(total_steps + BATCH_SIZE - 1) // BATCH_SIZE}")
        if pushed_root:
            print(f"  Server root: {pushed_root}")
            
    except Exception as e:
        print(f"\nError: Failed to push session: {e}", file=sys.stderr)
        sys.exit(1)


def _push_reset(session_id: str, reset_to: str | None = None) -> None:
    """Reset local push tracking so the session can be re-pushed."""
    store = SessionStore()
    meta = store.read_session_meta(session_id)
    if not meta:
        print(f"Error: Session {session_id} not found.", file=sys.stderr)
        sys.exit(1)

    remote = meta.get("remote", {})

    if reset_to:
        # Validate that the step_id actually exists in the session
        steps_file = store.paths.sessions_dir / session_id / "steps.jsonl"
        step_ids = []
        if steps_file.exists():
            with open(steps_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    step_ids.append(json.loads(line).get("id"))

        if reset_to not in step_ids:
            print(f"Error: Step '{reset_to}' not found in session {session_id}.", file=sys.stderr)
            print(f"  Available steps: {', '.join(step_ids[:5])}{'...' if len(step_ids) > 5 else ''}", file=sys.stderr)
            sys.exit(1)

        remote["last_pushed_step_id"] = reset_to
        print(f"Reset push state for {session_id} to step {reset_to}.")
        print(f"  Steps after '{reset_to}' will be pushed on next `mach push`.")
    else:
        # Full reset — clear all push tracking
        remote["last_pushed_step_id"] = None
        remote["pushed_root"] = None
        remote["last_pushed_ts"] = 0
        remote["last_push_id"] = None
        remote["server_session_id"] = None
        remote["server_root_before"] = None
        remote["server_root_after"] = None
        remote["blobs_received"] = None
        remote["steps_received"] = None
        print(f"Fully reset push state for {session_id}.")
        print(f"  All steps will be pushed on next `mach push`.")

    meta["remote"] = remote
    store.update_push_state(
        session_id,
        remote_updates=remote,
    )


def pull_command(args: argparse.Namespace) -> None:
    """Check the backend for current server state and reconcile local tracking."""
    token = get_token()
    if not token:
        print("Error: You must log in first. Run: mach login", file=sys.stderr)
        sys.exit(1)

    session_id = args.session_id
    store = SessionStore()
    meta = store.read_session_meta(session_id)
    if not meta:
        print(f"Error: Session {session_id} not found locally.", file=sys.stderr)
        sys.exit(1)

    config = store.read_config()
    base_url = config.get("api_base_url", "http://localhost:8000").rstrip("/")
    endpoint = f"{base_url}/api/v1/sessions/{session_id}/status/"

    req = urllib.request.Request(
        endpoint,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req) as response:
            resp_body = response.read().decode("utf-8")
            server_state = json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as http_err:
        if http_err.code == 404:
            # Session doesn't exist on server — reset local tracking
            print(f"Session {session_id} not found on server. Resetting local push state...")
            _push_reset(session_id, reset_to=None)
            return
        body = http_err.read().decode("utf-8", errors="replace")
        print(f"Error: Backend returned status {http_err.code}", file=sys.stderr)
        if body:
            print(body, file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as req_err:
        print(f"Error: Could not connect to backend ({endpoint}): {req_err}", file=sys.stderr)
        sys.exit(1)

    # Read local steps to compare
    steps_file = store.paths.sessions_dir / session_id / "steps.jsonl"
    local_step_ids = []
    if steps_file.exists():
        with open(steps_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                local_step_ids.append(json.loads(line).get("id"))

    server_step_count = server_state.get("step_count", 0)
    server_merkle = server_state.get("merkle_root")
    server_last_step = server_state.get("last_step", {})
    server_last_step_id = server_last_step.get("step_id") or server_last_step.get("mach_id")
    local_total = len(local_step_ids)

    print(f"Pull status for session {session_id}:")
    print(f"  Local steps:  {local_total}")
    print(f"  Server steps: {server_step_count}")

    if server_merkle:
        # Read local merkle for comparison
        merkle_path = store.paths.sessions_dir / session_id / "merkle.sig"
        local_merkle = {}
        if merkle_path.exists():
            with open(merkle_path, "r", encoding="utf-8") as f:
                local_merkle = json.load(f)
        local_root = local_merkle.get("root")
        if local_root == server_merkle:
            print(f"  Merkle roots match: {server_merkle[:16]}...")
        else:
            print(f"  Merkle DIVERGED:")
            print(f"    Local:  {local_root[:16] if local_root else '(none)'}...")
            print(f"    Server: {server_merkle[:16]}...")

    # Determine how many steps are unpushed
    if server_last_step_id and server_last_step_id in local_step_ids:
        idx = local_step_ids.index(server_last_step_id)
        unpushed = local_total - idx - 1
        print(f"  Server has up to step: {server_last_step_id}")
        print(f"  Unpushed steps: {unpushed}")

        # Update local tracking to match server state
        store.update_push_state(
            session_id,
            remote_updates={
                "last_pushed_step_id": server_last_step_id,
                "pushed_root": server_merkle,
                "last_pushed_ts": int(time.time()),
                "server_session_id": server_state.get("id"),
            },
            step_count=server_step_count,
        )
        print(f"  Local push state synchronized with server.")
        if unpushed > 0:
            print(f"  Run `mach push {session_id}` to push remaining {unpushed} steps.")
    elif server_step_count == 0:
        # Server has no steps — full reset so everything can be pushed
        print(f"  Server has no steps. Resetting local push state for full re-push...")
        _push_reset(session_id, reset_to=None)
        print(f"  Run `mach push {session_id}` to push all {local_total} steps.")
    else:
        # Server has steps but we can't correlate — warn the user
        print(f"  Warning: Could not correlate server state with local steps.")
        print(f"  Server last step: {server_last_step_id or '(unknown)'}")
        print(f"  Consider `mach push --reset {session_id}` for a full re-push.")


def _format_push_step(store: SessionStore, step: dict, blobs: dict[str, str]) -> dict:
    content_hash = step.get("content_hash")
    _collect_blob(store, blobs, content_hash, step.get("content"))

    tool = step.get("tool")
    formatted_tool = None
    if tool:
        tool_hash = tool.get("content_hash")
        _collect_blob(store, blobs, tool_hash, tool.get("content"))
        formatted_tool = {
            "name": tool.get("name"),
            "category": tool.get("category", "exec"),
            "content_hash": tool_hash,
        }

    payload = {
        "id": step.get("id"),
        "step_num": step.get("step_num"),
        "ts": step.get("ts"),
        "type": step.get("type"),
        "content_hash": content_hash,
        "caused_by": step.get("caused_by", []),
        "risk_level": step.get("risk_level", "none"),
        "tool": formatted_tool,
        "file_changes": [_format_push_file_change(store, change) for change in step.get("file_changes", [])],
        "risk_flags": step.get("risk_flags", []),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _format_push_file_change(store: SessionStore, change: dict) -> dict:
    formatted = dict(change)
    file_path = formatted.get("file_path")
    if file_path:
        path = Path(file_path)
        if path.is_absolute():
            try:
                formatted["file_path"] = str(path.relative_to(store.paths.repo_root))
            except ValueError:
                formatted["file_path"] = str(path)
    return formatted


def _collect_blob(store: SessionStore, blobs: dict[str, str], content_hash: str | None, inline_content: str | None = None) -> None:
    if not content_hash:
        return
    content = inline_content if inline_content is not None else store._read_blob(content_hash)
    if content is not None:
        blobs[content_hash] = content


def _push_host_name() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return sys.platform


def _agent_provider(agent_name: str) -> str:
    """Map agent name to its provider for the push payload."""
    mapping = {
        "gemini": "google",
        "claude": "anthropic",
        "codex": "openai",
        "copilot": "github",
        "cursor": "anysphere",
    }
    return mapping.get(agent_name.lower(), "unknown")




def update_command(_: argparse.Namespace) -> None:
    import subprocess
    install_dir = Path.home() / ".mach"
    if not install_dir.exists() or not (install_dir / ".git").exists():
        print("Error: Mach is not installed globally at ~/.mach or is not a git repository.", file=sys.stderr)
        sys.exit(1)
        
    print("Updating Mach...")
    try:
        subprocess.check_call(
            ["git", "pull", "origin", "master"],
            cwd=str(install_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Also update the python environment if it exists
        venv_pip = install_dir / "venv" / "bin" / "pip"
        if venv_pip.exists():
            subprocess.check_call(
                [str(venv_pip), "install", "--upgrade", "."],
                cwd=str(install_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
        print("Success: Mach updated successfully.")
    except subprocess.CalledProcessError:
        print("Error: Failed to update Mach.", file=sys.stderr)
        sys.exit(1)


def config_show_command(args: argparse.Namespace) -> None:
    config = SessionStore().read_config()
    if getattr(args, "json", False):
        emit(config)
    else:
        print("Mach Configuration:")
        print("-" * 50)
        for key, value in sorted(config.items()):
            print(f"{key:25} : {value}")


def config_set_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    current = store.read_config()
    updates = {}

    if args.enable:
        updates["enabled"] = True
    if args.disable:
        updates["enabled"] = False
    if args.auto_tracking is not None:
        updates["auto_tracking"] = args.auto_tracking == "true"
    if args.commit_closes_session is not None:
        updates["commit_closes_session"] = args.commit_closes_session == "true"
    if args.idle_timeout_sec is not None:
        updates["idle_timeout_sec"] = None if args.idle_timeout_sec == "none" else int(args.idle_timeout_sec)
    if args.poll_interval_sec is not None:
        updates["poll_interval_sec"] = float(args.poll_interval_sec)
    if args.store_content is not None:
        updates["store_content"] = [t.strip() for t in args.store_content.split(",") if t.strip()]
    if args.use_tui is not None:
        updates["use_tui"] = args.use_tui == "true"
    if args.db_enabled is not None:
        updates["db_enabled"] = args.db_enabled == "true"

    hook_agents = list(current.get("hook_agents") or [])
    if args.hook_agents is not None:
        hook_agents = [agent for agent in args.hook_agents.split(",") if agent]
    if args.add_agent:
        for agent in args.add_agent:
            if agent not in hook_agents:
                hook_agents.append(agent)
    if args.remove_agent:
        hook_agents = [agent for agent in hook_agents if agent not in set(args.remove_agent)]
    if args.hook_agents is not None or args.add_agent or args.remove_agent:
        updates["hook_agents"] = hook_agents

    config = store.update_config(updates) if updates else current

    manager = HookManager()
    hook_result = None
    tracking_result = None

    if args.refresh_hooks:
        hook_result = manager.uninstall(["all"])
        hook_result = {
            "uninstalled": hook_result["uninstalled"],
            "installed": manager.install(config.get("hook_agents") or []).get("installed", []),
        }
    elif args.apply and config.get("enabled", True):
        hook_result = manager.install(config.get("hook_agents") or [])
    elif args.apply and not config.get("enabled", True):
        hook_result = manager.uninstall(["all"])

    if args.apply:
        tracker = TrackerService()
        if config.get("enabled", True) and config.get("auto_tracking", True):
            tracker.ensure_state()
            tracking_result = tracker.start_daemon()
        else:
            tracking_result = tracker.stop_daemon()

    print("Success: Configuration applied.")


def session_start(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.start_session(agent=args.agent, task_desc=args.task_desc))


def session_end(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.end_session(session_id=args.session_id))


def log_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    if hasattr(args, "session_id") and args.session_id:
        data = store.show_session(session_id=args.session_id)
        if getattr(args, "json", False):
            emit(data)
        elif getattr(args, "content", False):
            pydoc.pager(format_session_details(data, patch=getattr(args, "patch", False)))
        else:
            pydoc.pager(format_session_steps(data, oneline=getattr(args, "oneline", False), patch=getattr(args, "patch", False)))
    else:
        sessions = store.list_sessions()
        import sys
        if getattr(args, "json", False):
            emit(sessions)
        elif sys.stdout.isatty() and not getattr(args, "no_tui", False) and store.get_config().get("use_tui", True):
            from mach.tui import run_tui
            run_tui(store)
        else:
            pydoc.pager(format_sessions_list(sessions))


def show_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    data = store.show_session(session_id=args.session_id)
    if getattr(args, "json", False):
        emit(data)
    else:
        pydoc.pager(format_session_details(data, patch=getattr(args, "patch", False)))


def verify_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    if args.session_id:
        emit(store.verify_session(args.session_id))
    else:
        emit(store.verify_all())


def on_commit_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.on_commit())


def fsck_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.fsck())


def rewind_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.rewind(target=args.target))


def resume_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.resume_branch(branch=args.branch))


def clean_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.clean(max_days=int(args.max_days)))


def doctor_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    fsck_res = store.fsck()
    tracker = TrackerService()
    if tracker.status().get("running"):
        tracker.stop_daemon()
    t_res = tracker.start_daemon()
    emit({"fsck": fsck_res, "tracker": t_res})


def ingest_event_command(args: argparse.Namespace) -> None:
    ingest = EventInboxService()
    step: dict[str, object] = {
        "type": args.step_type,
        "content": args.content,
    }
    if args.tool_name or args.tool_category or args.tool_content:
        step["tool"] = {
            "name": args.tool_name,
            "category": args.tool_category,
            "content": args.tool_content,
        }
    if args.risk_level:
        step["risk_level"] = args.risk_level

    payload = {
        "kind": "step",
        "agent": args.agent,
        "source_session_id": args.source_session_id,
        "task_desc": args.task_desc,
        "end_session": args.end_session,
        "step": step,
    }
    result = ingest.enqueue_event(payload, stream=args.stream)
    if args.process_now:
        result["processed"] = ingest.process_pending_events()
    emit(result)


def ingest_end_command(args: argparse.Namespace) -> None:
    ingest = EventInboxService()
    result = ingest.enqueue_event(
        {
            "kind": "session_end",
            "agent": args.agent,
            "source_session_id": args.source_session_id,
        },
        stream=args.stream,
    )
    if args.process_now:
        result["processed"] = ingest.process_pending_events()
    emit(result)


def ingest_process_command(_: argparse.Namespace) -> None:
    ingest = EventInboxService()
    emit(ingest.process_pending_events())


def hooks_install_command(args: argparse.Namespace) -> None:
    manager = HookManager()
    emit(manager.install(args.agents))


def hooks_uninstall_command(args: argparse.Namespace) -> None:
    manager = HookManager()
    emit(manager.uninstall(args.agents))


def hooks_status_command(args: argparse.Namespace) -> None:
    manager = HookManager()
    emit(manager.status(args.agents))


def hooks_dispatch_command(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root) if args.repo_root else None
    raw_payload = sys.stdin.read()
    try:
        manager = HookManager(repo_root=repo_root)
        result = manager.dispatch(
            agent=args.agent,
            event_name=args.event,
            raw_payload=raw_payload,
            repo_root=repo_root,
        )
    except Exception:
        if args.stdout_mode == "empty-json":
            sys.stdout.write("{}")
            return
        raise
    if args.stdout_mode == "empty-json":
        sys.stdout.write(result.emitted_output or "{}")
    elif args.stdout_mode == "passthrough" and result.emitted_output:
        sys.stdout.write(result.emitted_output)


def track_start_command(_: argparse.Namespace) -> None:
    tracker = TrackerService()
    emit(tracker.start_daemon())


def track_stop_command(_: argparse.Namespace) -> None:
    tracker = TrackerService()
    emit(tracker.stop_daemon())


def track_status_command(_: argparse.Namespace) -> None:
    tracker = TrackerService()
    emit(tracker.status())


def track_scan_command(_: argparse.Namespace) -> None:
    tracker = TrackerService()
    emit(tracker.scan_once())


def track_run_command(args: argparse.Namespace) -> None:
    tracker = TrackerService(repo_root=Path(args.repo_root))
    emit(tracker.run_loop(once=args.once))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mach",
        description="Local-first execution logging for AI agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize .mach metadata.")
    init_parser.add_argument("--hook-agents", help="Comma-separated agents to install without prompting.")
    init_parser.set_defaults(handler=init_command)

    enable_parser = subparsers.add_parser("enable", help="Enable Mach hooks and background tracking in this repo.")
    enable_parser.set_defaults(handler=enable_command)

    disable_parser = subparsers.add_parser("disable", help="Disable Mach hooks and background tracking in this repo.")
    disable_parser.set_defaults(handler=disable_command)

    session_parser = subparsers.add_parser("session", help="Manage sessions.")
    session_subparsers = session_parser.add_subparsers(dest="session_command", required=True)

    session_start_parser = session_subparsers.add_parser("start", help="Start a session.")
    session_start_parser.add_argument("--agent", default="unknown")
    session_start_parser.add_argument("--task-desc")
    session_start_parser.set_defaults(handler=session_start)

    session_end_parser = session_subparsers.add_parser("end", help="End a session.")
    session_end_parser.add_argument("session_id", nargs="?")
    session_end_parser.set_defaults(handler=session_end)

    log_parser = subparsers.add_parser("log", help="List known sessions or view a specific session.")
    log_parser.add_argument("session_id", nargs="?", help="Specific session ID to view.")
    log_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    log_parser.add_argument("--content", action="store_true", help="Show full content transcript instead of summary.")
    log_parser.add_argument("--oneline", action="store_true", help="Format steps as a single line.")
    log_parser.add_argument("--patch", "-p", action="store_true", help="Show file changes and hunks.")
    log_parser.add_argument("--no-tui", action="store_true", help="Use static pager output instead of interactive TUI.")
    log_parser.set_defaults(handler=log_command)

    show_parser = subparsers.add_parser("show", help="Show a session.")
    show_parser.add_argument("session_id", nargs="?", help="Session ID to show.")
    show_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    show_parser.add_argument("--patch", "-p", action="store_true", help="Show file changes and hunks.")
    show_parser.set_defaults(handler=show_command)

    verify_parser = subparsers.add_parser("verify", help="Verify Merkle integrity.")
    verify_parser.add_argument("session_id", nargs="?")
    verify_parser.set_defaults(handler=verify_command)

    fsck_parser = subparsers.add_parser("fsck", help="Rebuild the SQLite index from JSONL logs.")
    fsck_parser.set_defaults(handler=fsck_command)

    rewind_parser = subparsers.add_parser("rewind", help="Rewind workspace to target commit in append-only mode.")
    rewind_parser.add_argument("target", help="Commit hash or branch name to rewind to.")
    rewind_parser.set_defaults(handler=rewind_command)

    resume_parser = subparsers.add_parser("resume", help="Resume latest session on active branch.")
    resume_parser.add_argument("branch", nargs="?", help="Specific branch to resume on.")
    resume_parser.set_defaults(handler=resume_command)

    clean_parser = subparsers.add_parser("clean", help="Clean orphaned AI sessions.")
    clean_parser.add_argument("--max-days", default=7, type=int, help="Delete sessions older than max days without a commit.")
    clean_parser.set_defaults(handler=clean_command)

    doctor_parser = subparsers.add_parser("doctor", help="Fix broken sessions and restart trackers.")
    doctor_parser.set_defaults(handler=doctor_command)

    on_commit_parser = subparsers.add_parser("on-commit", help="Close active session after a commit.")
    on_commit_parser.set_defaults(handler=on_commit_command)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest AI-agent events into Mach.")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", required=True)

    ingest_event_parser = ingest_subparsers.add_parser("event", help="Queue a structured AI activity event.")
    ingest_event_parser.add_argument("--agent", required=True)
    ingest_event_parser.add_argument("--source-session-id")
    ingest_event_parser.add_argument("--task-desc")
    ingest_event_parser.add_argument("--type", dest="step_type", required=True)
    ingest_event_parser.add_argument("--content", default="")
    ingest_event_parser.add_argument("--tool-name")
    ingest_event_parser.add_argument("--tool-category")
    ingest_event_parser.add_argument("--tool-content")
    ingest_event_parser.add_argument("--risk-level")
    ingest_event_parser.add_argument("--stream", default="events")
    ingest_event_parser.add_argument("--end-session", action="store_true")
    ingest_event_parser.add_argument("--process-now", action="store_true")
    ingest_event_parser.set_defaults(handler=ingest_event_command)

    ingest_end_parser = ingest_subparsers.add_parser("end", help="Queue an agent session end event.")
    ingest_end_parser.add_argument("--agent", required=True)
    ingest_end_parser.add_argument("--source-session-id")
    ingest_end_parser.add_argument("--stream", default="events")
    ingest_end_parser.add_argument("--process-now", action="store_true")
    ingest_end_parser.set_defaults(handler=ingest_end_command)

    ingest_process_parser = ingest_subparsers.add_parser("process", help="Process queued AI events now.")
    ingest_process_parser.set_defaults(handler=ingest_process_command)

    hooks_parser = subparsers.add_parser("hooks", help="Install and manage agent hook integrations.")
    hooks_subparsers = hooks_parser.add_subparsers(dest="hooks_command", required=True)

    hooks_install_parser = hooks_subparsers.add_parser("install", help="Install Mach hooks for supported agents.")
    hooks_install_parser.add_argument("agents", nargs="*", default=["all"])
    hooks_install_parser.set_defaults(handler=hooks_install_command)

    hooks_uninstall_parser = hooks_subparsers.add_parser("uninstall", help="Remove Mach hooks for agents.")
    hooks_uninstall_parser.add_argument("agents", nargs="*", default=["all"])
    hooks_uninstall_parser.set_defaults(handler=hooks_uninstall_command)

    hooks_status_parser = hooks_subparsers.add_parser("status", help="Show hook installation status.")
    hooks_status_parser.add_argument("agents", nargs="*", default=["all"])
    hooks_status_parser.set_defaults(handler=hooks_status_command)

    hooks_dispatch_parser = hooks_subparsers.add_parser("dispatch", help="Internal: receive a vendor hook payload on stdin.")
    hooks_dispatch_parser.add_argument("--agent", required=True)
    hooks_dispatch_parser.add_argument("--event", required=True)
    hooks_dispatch_parser.add_argument("--repo-root", default=".")
    hooks_dispatch_parser.add_argument("--stdout-mode", choices=["silent", "empty-json", "passthrough"], default="silent")
    hooks_dispatch_parser.set_defaults(handler=hooks_dispatch_command)

    config_parser = subparsers.add_parser("config", help="Show or update Mach configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)

    config_show_parser = config_subparsers.add_parser("show", help="Show merged Mach config.")
    config_show_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    config_show_parser.set_defaults(handler=config_show_command)

    config_set_parser = config_subparsers.add_parser("set", help="Update Mach config values.")
    config_set_parser.add_argument("--enable", action="store_true")
    config_set_parser.add_argument("--disable", action="store_true")
    config_set_parser.add_argument("--auto-tracking", choices=["true", "false"])
    config_set_parser.add_argument("--commit-closes-session", choices=["true", "false"])
    config_set_parser.add_argument("--idle-timeout-sec")
    config_set_parser.add_argument("--poll-interval-sec")
    config_set_parser.add_argument("--hook-agents")
    config_set_parser.add_argument("--add-agent", action="append")
    config_set_parser.add_argument("--remove-agent", action="append")
    config_set_parser.add_argument("--store-content", help="Comma-separated step types to store content for (e.g. input,reasoning,tool,output)")
    config_set_parser.add_argument("--use-tui", choices=["true", "false"])
    config_set_parser.add_argument("--db-enabled", choices=["true", "false"])
    config_set_parser.add_argument("--apply", action="store_true", help="Apply current config to hooks and tracker after updating.")
    config_set_parser.add_argument("--refresh-hooks", action="store_true", help="Reinstall managed hooks after updating config.")
    config_set_parser.set_defaults(handler=config_set_command)

    track_parser = subparsers.add_parser("track", help="Manage automatic repository tracking.")
    track_subparsers = track_parser.add_subparsers(dest="track_command", required=True)

    track_start_parser = track_subparsers.add_parser("start", help="Start the background tracker.")
    track_start_parser.set_defaults(handler=track_start_command)

    track_stop_parser = track_subparsers.add_parser("stop", help="Stop the background tracker.")
    track_stop_parser.set_defaults(handler=track_stop_command)

    track_status_parser = track_subparsers.add_parser("status", help="Show tracker status.")
    track_status_parser.set_defaults(handler=track_status_command)

    track_scan_parser = track_subparsers.add_parser("scan", help="Run one tracking scan immediately.")
    track_scan_parser.set_defaults(handler=track_scan_command)

    track_run_parser = track_subparsers.add_parser("run", help="Run the tracker loop.")
    track_run_parser.add_argument("--repo-root", default=".")
    track_run_parser.add_argument("--once", action="store_true")
    track_run_parser.set_defaults(handler=track_run_command)

    # Alias `mach session <id>` to `mach show <id>` implicitly.
    if len(sys.argv) >= 3 and sys.argv[1] == "session" and sys.argv[2] not in ("start", "end", "-h", "--help"):
        sys.argv[1] = "show"

    login_parser = subparsers.add_parser("login", help="Authenticate with the Mach web platform.")
    login_parser.add_argument("--token", help="Your Personal Access Token.")
    login_parser.set_defaults(handler=login_command)

    logout_parser = subparsers.add_parser("logout", help="Log out of the Mach web platform.")
    logout_parser.set_defaults(handler=logout_command)

    push_parser = subparsers.add_parser("push", help="Push a session to the Mach web platform.")
    push_parser.add_argument("session_id", help="The ID of the session to push.")
    push_parser.add_argument("--reset", action="store_true", help="Reset local push tracking so the session can be re-pushed.")
    push_parser.add_argument("--reset-to", metavar="STEP_ID", help="Reset push state to a specific step ID (re-push steps after it).")
    push_parser.set_defaults(handler=push_command)

    pull_parser = subparsers.add_parser("pull", help="Check server state for a session and reconcile local tracking.")
    pull_parser.add_argument("session_id", help="The ID of the session to check.")
    pull_parser.set_defaults(handler=pull_command)

    update_parser = subparsers.add_parser("update", help="Update the global Mach installation to the latest version.")
    update_parser.set_defaults(handler=update_command)

    try:
        args = parser.parse_args()
        args.handler(args)
    except MachError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
