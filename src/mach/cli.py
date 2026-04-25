from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mach.hooks import HookManager
from mach.ingest import EventInboxService
from mach.session import MachError, SessionStore
from mach.tracker import TrackerService

def emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


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


def log_command(_: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.list_sessions())


def show_command(args: argparse.Namespace) -> None:
    store = SessionStore()
    emit(store.show_session(session_id=args.session_id))


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

    log_parser = subparsers.add_parser("log", help="List known sessions.")
    log_parser.set_defaults(handler=log_command)

    show_parser = subparsers.add_parser("show", help="Show a session.")
    show_parser.add_argument("session_id", nargs="?")
    show_parser.set_defaults(handler=show_command)

    verify_parser = subparsers.add_parser("verify", help="Verify Merkle integrity.")
    verify_parser.add_argument("session_id", nargs="?")
    verify_parser.set_defaults(handler=verify_command)

    fsck_parser = subparsers.add_parser("fsck", help="Rebuild the SQLite index from JSONL logs.")
    fsck_parser.set_defaults(handler=fsck_command)

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

    try:
        args = parser.parse_args()
        args.handler(args)
    except MachError as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    main()
