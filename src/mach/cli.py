from __future__ import annotations

import argparse
import json
import sys
import pydoc
from pathlib import Path

from mach.hooks import HookManager
from mach.ingest import EventInboxService
from mach.session import MachError, SessionStore
from mach.tracker import TrackerService

def emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))

def format_sessions_list(sessions: list[dict]) -> str:
    if not sessions:
        return "No sessions found.\n"
    out = ["\n\033[1mTracking Sessions\033[0m\n"]
    for s in sessions:
        status = s.get("status") or ("active" if s.get("ended_at") is None else "ended")
        color = "\033[92m" if status == "active" else "\033[90m"
        agent = s.get("agent", "unknown")
        sid = s.get("id")
        commits = f"{str(s.get('pre_commit', ''))[:7]} -> {str(s.get('post_commit', ''))[:7] if s.get('post_commit') else 'pending'}"
        out.append(f"{color}* {sid}\033[0m")
        out.append(f"  Agent:  {agent}")
        out.append(f"  Status: {status}")
        out.append(f"  Branch: {s.get('branch')} ({commits})")
        out.append(f"  Steps:  {s.get('step_count', 0)}\n")
    return "\n".join(out)

def format_session_steps(data: dict, oneline: bool = False, patch: bool = False) -> str:
    import time
    meta = data["meta"]
    steps = data["steps"]
    
    out = []
    if not oneline:
        out.append(f"\n\033[1;34mSESSION: {meta.get('id')}\033[0m")
        out.append(f"Agent: {meta.get('agent')} | Branch: {meta.get('branch')} | Status: {meta.get('status', 'ended')}")
        out.append(f"Pre-commit: {meta.get('pre_commit')} | Post-commit: {meta.get('post_commit')}\n")
        out.append("\033[1mSession Timeline:\033[0m\n")
    
    coalesced = []
    for step in steps:
        stype = step.get("type", "unknown")
        content = step.get("content", "")
        tool = step.get("tool")
        
        if tool:
            tool_name = tool.get("name")
            # Coalesce consecutive identical tool calls (e.g. repeated workspace_observer)
            if coalesced and coalesced[-1]["type"] == "tool" and coalesced[-1].get("name") == tool_name:
                coalesced[-1]["id"] = step["id"]
                coalesced[-1]["ts"] = step["ts"]
                coalesced[-1]["count"] = coalesced[-1].get("count", 1) + 1
            else:
                coalesced.append({
                    "id": step["id"],
                    "ts": step["ts"],
                    "type": "tool",
                    "name": tool_name,
                    "content": tool.get("content", ""),
                    "file_changes": step.get("file_changes")
                })
            continue

        # Coalesce consecutive same-type non-tool steps
        if coalesced and coalesced[-1]["type"] == stype and coalesced[-1]["type"] != "tool":
            last = coalesced[-1]
            last["content"] = (last.get("content") or "") + (content or "")
            last["id"] = step["id"]
            last["ts"] = step["ts"]
        else:
            coalesced.append({
                "id": step["id"],
                "ts": step["ts"],
                "type": stype,
                "content": content or ""
            })
                
    for c in reversed(coalesced):
        stype = c["type"]
        sid = c["id"].replace("step_", "")
        ts_str = time.strftime('%a %b %d %H:%M:%S %Y %z', time.localtime(c["ts"]))
        
        agent_name = meta.get('agent', 'unknown')
        if stype == "input":
            agent_name = "user"
        elif stype == "system_action":
            agent_name = "system"
            
        if stype == "tool":
            count = c.get("count", 1)
            count_str = f" ×{count}" if count > 1 else ""
            text = f"Executed tool: {c.get('name')}{count_str}"
            fc = c.get("file_changes")
            if fc and patch:
                for change in fc:
                    fp = change.get('file_path', 'unknown')
                    name = Path(fp).name
                    text += f"\n\n    --- a/{name}"
                    text += f"\n    +++ b/{name}"
                    hunks = change.get('hunks', [])
                    for h in hunks:
                        start = h.get('from', 0)
                        end = h.get('to', 0)
                        lines = max(1, end - start + 1)
                        text += f"\n    @@ -{start},{lines} +{start},{lines} @@"
        else:
            text = str(c.get('content', '')).strip()
            first_line = text.split('\n')[0][:80]
            if len(text) > len(first_line) or len(text) > 80:
                first_line += "..."
            if not first_line:
                first_line = "(empty)"
            text = first_line

        if oneline:
            out.append(f"\033[33m{sid[:7]}\033[0m [{stype.upper()}] {text}")
        else:
            out.append(f"\033[33mstep {sid}\033[0m")
            out.append(f"Agent:  {agent_name}")
            out.append(f"Type:   {stype.upper()}")
            out.append(f"Date:   {ts_str}")
            out.append("")
            out.append(f"    {text}")
            out.append("")
            
    return "\n".join(out)

def format_session_details(data: dict, patch: bool = False) -> str:
    meta = data["meta"]
    steps = data["steps"]
    
    out = []
    out.append(f"\n\033[1;34mSESSION: {meta.get('id')}\033[0m")
    out.append(f"Agent: {meta.get('agent')} | Branch: {meta.get('branch')} | Status: {meta.get('status', 'ended')}")
    out.append(f"Pre-commit: {meta.get('pre_commit')} | Post-commit: {meta.get('post_commit')}\n")
    
    coalesced = []
    for step in steps:
        stype = step.get("type", "unknown")
        content = step.get("content", "")
        tool = step.get("tool")
        
        if tool:
            tool_name = tool.get("name")
            if coalesced and coalesced[-1]["type"] == "tool" and coalesced[-1].get("name") == tool_name:
                coalesced[-1]["count"] = coalesced[-1].get("count", 1) + 1
            else:
                coalesced.append({
                    "type": "tool",
                    "name": tool_name,
                    "content": f"Used tool '{tool_name}': {tool.get('content', '')}",
                    "file_changes": step.get("file_changes")
                })
            continue

        # Coalesce consecutive same-type non-tool steps
        if coalesced and coalesced[-1]["type"] == stype and coalesced[-1]["type"] != "tool":
            coalesced[-1]["content"] = (coalesced[-1].get("content") or "") + (content or "")
        else:
            coalesced.append({"type": stype, "content": content or ""})
                
    for c in coalesced:
        stype = c["type"]
        text = str(c["content"]).strip()
        if not text:
            continue
            
        fc = c.get("file_changes")
        if fc and patch:
            for change in fc:
                fp = change.get('file_path', 'unknown')
                name = Path(fp).name
                text += f"\n\n  --- a/{name}"
                text += f"\n  +++ b/{name}"
                hunks = change.get('hunks', [])
                for h in hunks:
                    start = h.get('from', 0)
                    end = h.get('to', 0)
                    lines = max(1, end - start + 1)
                    text += f"\n  @@ -{start},{lines} +{start},{lines} @@"
                
        if stype == "input":
            out.append(f"\033[1;32m> USER\033[0m\n{text}\n")
        elif stype == "reasoning":
            out.append(f"\033[90m> REASONING ({meta.get('agent')})\n{text}\033[0m\n")
        elif stype == "output":
            out.append(f"\033[1;36m> OUTPUT ({meta.get('agent')})\033[0m\n{text}\n")
        elif stype == "system_action":
            out.append(f"\033[1;33m> SYSTEM\033[0m\n{text}\n")
        elif stype == "tool":
            out.append(f"\033[1;35m> TOOL 🛠️\033[0m\n{text}\n")
        else:
            out.append(f"\033[1;37m> {stype.upper()}\033[0m\n{text}\n")
            
    return "\n".join(out)


def init_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    mach_dir = store.init_repo()
    config = store.update_config({"enabled": True})
    manager = HookManager()
    hook_results = manager.install(config.get("hook_agents") or manager.installable_agents())
    tracker = TrackerService()
    tracker.ensure_state()
    tracking = tracker.start_daemon() if config.get("auto_tracking", True) else tracker.status()
    emit({"initialized": True, "mach_dir": str(mach_dir), "tracking": tracking, "hooks": hook_results, "config": config})


def enable_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    config = store.update_config({"enabled": True})
    manager = HookManager()
    hook_results = manager.install(config.get("hook_agents") or manager.installable_agents())
    tracker = TrackerService()
    tracking = tracker.start_daemon() if config.get("auto_tracking", True) else tracker.status()
    emit({"enabled": True, "config": config, "hooks": hook_results, "tracking": tracking})


def disable_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    config = store.update_config({"enabled": False})
    hook_results = HookManager().uninstall(config.get("hook_agents"))
    tracking = TrackerService().stop_daemon()
    emit({"enabled": False, "config": config, "hooks": hook_results, "tracking": tracking})


def config_show_command(_: argparse.Namespace) -> None:
    emit(SessionStore().read_config())


def config_set_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    updates = {}
    if args.enabled is not None:
        updates["enabled"] = args.enabled == "true"
    if args.auto_tracking is not None:
        updates["auto_tracking"] = args.auto_tracking == "true"
    if args.commit_closes_session is not None:
        updates["commit_closes_session"] = args.commit_closes_session == "true"
    if args.idle_timeout_sec is not None:
        updates["idle_timeout_sec"] = None if args.idle_timeout_sec == "none" else int(args.idle_timeout_sec)
    if args.poll_interval_sec is not None:
        updates["poll_interval_sec"] = float(args.poll_interval_sec)
    if args.hook_agents is not None:
        updates["hook_agents"] = [agent for agent in args.hook_agents.split(",") if agent]
    emit(store.update_config(updates))


def configure_command(args: argparse.Namespace) -> None:
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

    emit({
        "configured": True,
        "config": config,
        "hooks": hook_result,
        "tracking": tracking_result,
    })


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
        if getattr(args, "json", False):
            emit(sessions)
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
    manager = HookManager(repo_root=Path(args.repo_root))
    raw_payload = sys.stdin.read()
    result = manager.dispatch(
        agent=args.agent,
        event_name=args.event,
        raw_payload=raw_payload,
        repo_root=Path(args.repo_root),
    )
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
    init_parser.set_defaults(handler=init_command)

    enable_parser = subparsers.add_parser("enable", help="Enable Mach hooks and background tracking in this repo.")
    enable_parser.set_defaults(handler=enable_command)

    disable_parser = subparsers.add_parser("disable", help="Disable Mach hooks and background tracking in this repo.")
    disable_parser.set_defaults(handler=disable_command)

    configure_parser = subparsers.add_parser("configure", help="High-level setup command for managed agents, hooks, and tracking.")
    configure_parser.add_argument("--enable", action="store_true")
    configure_parser.add_argument("--disable", action="store_true")
    configure_parser.add_argument("--auto-tracking", choices=["true", "false"])
    configure_parser.add_argument("--commit-closes-session", choices=["true", "false"])
    configure_parser.add_argument("--idle-timeout-sec")
    configure_parser.add_argument("--poll-interval-sec")
    configure_parser.add_argument("--hook-agents")
    configure_parser.add_argument("--add-agent", action="append")
    configure_parser.add_argument("--remove-agent", action="append")
    configure_parser.add_argument("--store-content", help="Comma-separated step types to store content for (e.g. input,reasoning,tool,output)")
    configure_parser.add_argument("--apply", action="store_true", help="Apply current config to hooks and tracker after updating.")
    configure_parser.add_argument("--refresh-hooks", action="store_true", help="Reinstall managed hooks after updating config.")
    configure_parser.set_defaults(handler=configure_command)

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
    config_show_parser.set_defaults(handler=config_show_command)

    config_set_parser = config_subparsers.add_parser("set", help="Update Mach config values.")
    config_set_parser.add_argument("--enabled", choices=["true", "false"])
    config_set_parser.add_argument("--auto-tracking", choices=["true", "false"])
    config_set_parser.add_argument("--commit-closes-session", choices=["true", "false"])
    config_set_parser.add_argument("--idle-timeout-sec")
    config_set_parser.add_argument("--poll-interval-sec")
    config_set_parser.add_argument("--hook-agents")
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

    try:
        args = parser.parse_args()
        args.handler(args)
    except MachError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
