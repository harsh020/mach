from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mach.session import MachError, SessionStore
from mach.utils import append_jsonl, read_json, write_json


class EventInboxService:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.store = SessionStore(repo_root)
        self.paths = self.store.paths

    def ensure_files(self) -> None:
        self.store.init_repo()

    def enqueue_event(self, event: dict[str, Any], stream: str = "events") -> dict[str, Any]:
        self.ensure_files()
        stream_name = self._normalize_stream(stream)
        event = dict(event)
        event.setdefault("v", 1)
        event.setdefault("kind", "step")
        append_jsonl(self.paths.inbox_dir / f"{stream_name}.jsonl", event)
        return {
            "queued": True,
            "stream": stream_name,
            "inbox_file": str(self.paths.inbox_dir / f"{stream_name}.jsonl"),
        }

    def submit_event(self, event: dict[str, Any]) -> dict[str, Any]:
        self.ensure_files()
        return self._process_event(event)

    def process_pending_events(self) -> dict[str, Any]:
        self.ensure_files()
        state = read_json(self.paths.ingest_state_path)
        files_state = dict(state.get("files", {}))
        processed = 0
        events: list[dict[str, Any]] = []

        for inbox_file in sorted(self.paths.inbox_dir.glob("*.jsonl")):
            offset = int(files_state.get(inbox_file.name, 0))
            with inbox_file.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    raw = line.strip()
                    if not raw:
                        continue
                    payload = json.loads(raw)
                    result = self._process_event(payload)
                    processed += 1
                    events.append(result)
                files_state[inbox_file.name] = handle.tell()

        write_json(self.paths.ingest_state_path, {"files": files_state})
        return {"processed": processed, "events": events}

    def _process_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = payload.get("kind", "step")
        agent = payload.get("agent")
        if not agent:
            raise MachError("Ingested events must include 'agent'.")

        source_session_id = payload.get("source_session_id")
        task_desc = payload.get("task_desc")

        if kind == "session_end":
            meta = self.store.end_agent_session(agent=agent, source_session_id=source_session_id)
            return {
                "kind": "session_end",
                "agent": agent,
                "source_session_id": source_session_id,
                "session_id": meta["id"],
            }

        if kind != "step":
            raise MachError(f"Unsupported event kind: {kind}")

        step = payload.get("step")
        if not isinstance(step, dict):
            raise MachError("Step events must include a 'step' object.")

        recorded = self.store.record_agent_step(
            agent=agent,
            source_session_id=source_session_id,
            task_desc=task_desc,
            step_dict=step,
            end_session=bool(payload.get("end_session")),
        )
        return {
            "kind": "step",
            "agent": agent,
            "source_session_id": source_session_id,
            "session_id": recorded["session_id"],
            "step_id": recorded["id"],
            "step_type": recorded["type"],
        }

    @staticmethod
    def _normalize_stream(stream: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in stream)
        return cleaned or "events"
