from __future__ import annotations

import uuid
from pathlib import Path
from time import time
from typing import Any

from mach.config import DEFAULT_CONFIG, merge_config
from mach.db import connect, init_db, reset_db
from mach.git_utils import current_branch, head_commit
from mach.locking import file_lock
from mach.merkle import chain_hash, hash_payload
from mach.repository import resolve_paths
from mach.utils import (
    append_jsonl,
    canonical_json,
    ensure_json_file,
    read_json,
    read_jsonl,
    write_json,
)


class MachError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.paths = resolve_paths(repo_root)

    def get_config(self) -> dict:
        if not self.paths.config_path.exists():
            return DEFAULT_CONFIG
        return merge_config(read_json(self.paths.config_path))

    def init_repo(self) -> Path:
        self.paths.mach_dir.mkdir(parents=True, exist_ok=True)
        self.paths.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.paths.pack_dir.mkdir(parents=True, exist_ok=True)
        self.paths.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.paths.blobs_dir.mkdir(parents=True, exist_ok=True)
        ensure_json_file(self.paths.config_path, DEFAULT_CONFIG)
        ensure_json_file(self.paths.agent_sessions_path, {})
        ensure_json_file(self.paths.ingest_state_path, {"files": {}})
        self._write_config(merge_config(read_json(self.paths.config_path)))
        if not self.paths.head_path.exists():
            self.paths.head_path.write_text("", encoding="utf-8")
        init_db(self.paths.db_path)
        return self.paths.mach_dir

    def start_session(self, agent: str = "unknown", task_desc: str | None = None) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            return self._start_session_unlocked(agent=agent, task_desc=task_desc)

    def _start_session_unlocked(self, agent: str = "unknown", task_desc: str | None = None) -> dict[str, Any]:
        active = self.get_active_session_id()
        if active:
            return self.read_session_meta(active)

        return self._create_session_unlocked(agent=agent, task_desc=task_desc)

    def _check_concurrent_sessions(self, pre_commit: str | None) -> None:
        if not pre_commit:
            return
        try:
            with connect(self.paths.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM sessions WHERE ended_at IS NULL AND pre_commit = ?",
                    (pre_commit,)
                ).fetchone()
                if row and row["c"] > 0:
                    print(f"\033[93mWarning\033[0m: There are {row['c']} other active AI session(s) modifying this same commit state concurrently.")
        except Exception:
            pass  # fail gracefully if db not ready

    def _create_session_unlocked(self, agent: str = "unknown", task_desc: str | None = None, agent_session_id: str | None = None) -> dict[str, Any]:
        session_id = f"ses_{uuid.uuid4().hex}"
        session_dir = self.paths.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        pre_commit = head_commit(self.paths.repo_root)
        self._check_concurrent_sessions(pre_commit)

        meta = {
            "id": session_id,
            "started_at": int(time()),
            "ended_at": None,
            "agent": agent,
            "branch": current_branch(self.paths.repo_root),
            "pre_commit": pre_commit,
            "post_commit": None,
            "task_desc": task_desc,
            "status": "active",
            "agent_session_id": agent_session_id,
        }
        write_json(session_dir / "meta.json", meta)
        write_json(session_dir / "merkle.sig", {"root": None, "steps": 0})
        (session_dir / "steps.jsonl").touch()
        self.paths.head_path.write_text(session_id, encoding="utf-8")
        self._upsert_session_index(meta, step_count=0, risk_count=0)
        return meta

    def end_session(self, session_id: str | None = None) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            return self._end_session_unlocked(session_id=session_id)

    def _end_session_unlocked(self, session_id: str | None = None) -> dict[str, Any]:
        target_id = session_id or self.get_active_session_id()
        if not target_id:
            raise MachError("No active session to end.")

        meta = self.read_session_meta(target_id)
        if meta["status"] == "ended":
            return meta

        meta["ended_at"] = int(time())
        meta["status"] = "ended"
        meta["post_commit"] = head_commit(self.paths.repo_root)
        self._write_session_meta(meta)
        self._drop_agent_session_mapping_for_session(target_id)
        if self.get_active_session_id() == target_id:
            self.paths.head_path.write_text("", encoding="utf-8")
        self._upsert_session_index(
            meta,
            step_count=self._step_count(target_id),
            risk_count=self._risk_count(target_id),
        )
        return meta

    def get_active_session_id(self) -> str | None:
        if not self.paths.head_path.exists():
            return None
        raw = self.paths.head_path.read_text(encoding="utf-8").strip()
        return raw or None

    def record_step(self, step_dict: dict[str, Any]) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            active = self.get_active_session_id()
            session_id = active
            if not session_id:
                session_id = self._start_session_unlocked().get("id")

            meta = self.read_session_meta(session_id)
            if meta["status"] != "active":
                meta = self._start_session_unlocked(agent=meta.get("agent") or "unknown")
                session_id = meta["id"]

            return self._record_step_for_session_unlocked(session_id, step_dict)

    def record_agent_step(
        self,
        agent: str,
        step_dict: dict[str, Any],
        source_session_id: str | None = None,
        task_desc: str | None = None,
        end_session: bool = False,
    ) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            session_id = self._ensure_agent_session_unlocked(
                agent=agent,
                source_session_id=source_session_id,
                task_desc=task_desc,
            )
            payload = self._record_step_for_session_unlocked(session_id, step_dict)
            if end_session:
                self._end_session_unlocked(session_id)
            return payload

    def end_agent_session(self, agent: str, source_session_id: str | None = None) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            mappings = self._read_agent_sessions()
            key = self._agent_session_key(agent, source_session_id)
            session_id = mappings.get(key)
            if not session_id:
                raise MachError(f"No active mapped session for {key}.")
            ended = self._end_session_unlocked(session_id)
            self._drop_agent_session_mapping_for_session(session_id)
            return ended

    def verify_session(self, session_id: str) -> dict[str, Any]:
        if session_id == "HEAD":
            active = self.get_active_session_id()
            if not active:
                raise MachError("No active session exists.")
            session_id = active
        session_dir = self.paths.sessions_dir / session_id
        if not session_dir.exists():
            raise MachError(f"Unknown session: {session_id}")
        steps = read_jsonl(session_dir / "steps.jsonl")
        expected = read_json(session_dir / "merkle.sig")
        root = None
        for step in steps:
            root = chain_hash(step, root)
        return {
            "session_id": session_id,
            "valid": root == expected.get("root") and len(steps) == expected.get("steps"),
            "computed_root": root,
            "stored_root": expected.get("root"),
            "steps": len(steps),
        }

    def verify_all(self) -> list[dict[str, Any]]:
        self.init_repo()
        results = []
        for session_id in self._session_ids():
            results.append(self.verify_session(session_id))
        return results

    def list_sessions(self) -> list[dict[str, Any]]:
        self.init_repo()
        try:
            with connect(self.paths.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT id, started_at, ended_at, agent, agent_session_id, branch, pre_commit, post_commit,
                           step_count, risk_count, synced_at
                    FROM sessions
                    ORDER BY started_at DESC
                    """
                ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def show_session(self, session_id: str | None = None) -> dict[str, Any]:
        self.init_repo()
        target_id = self.get_active_session_id() if session_id in (None, "HEAD") else session_id
        if not target_id:
            raise MachError("No session specified and no active session exists.")
        meta = self.read_session_meta(target_id)
        session_dir = self.paths.sessions_dir / target_id
        steps = read_jsonl(session_dir / "steps.jsonl")
        
        # Hydrate steps with blob content
        for step in steps:
            if step.get("content") is None and step.get("content_hash"):
                blob_content = self._read_blob(step["content_hash"])
                if blob_content is not None:
                    step["content"] = blob_content
            if step.get("tool") and step["tool"].get("content") is None and step["tool"].get("content_hash"):
                blob_content = self._read_blob(step["tool"]["content_hash"])
                if blob_content is not None:
                    step["tool"]["content"] = blob_content

        return {
            "meta": meta,
            "merkle": read_json(session_dir / "merkle.sig"),
            "steps": steps,
        }

    def resume_branch(self, branch: str | None = None) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            target_branch = branch or current_branch(self.paths.repo_root)
            with connect(self.paths.db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM sessions WHERE branch = ? ORDER BY started_at DESC LIMIT 1",
                    (target_branch,)
                ).fetchone()
            
            if not row:
                raise MachError(f"No previous sessions found for branch: {target_branch}")
            
            session_id = row["id"]
            meta = self.read_session_meta(session_id)
            if meta["status"] != "active":
                meta["status"] = "active"
                meta["ended_at"] = None
                meta["post_commit"] = None
                self._write_session_meta(meta)
                self._upsert_session_index(meta, self._step_count(session_id), self._risk_count(session_id))
                # Record a system step to mark the resume event
                self._record_step_for_session_unlocked(session_id, {
                    "type": "system_action",
                    "content": f"Session resumed on branch {target_branch}",
                    "risk_level": "none",
                })
            
            self.paths.head_path.write_text(session_id, encoding="utf-8")
            
            agent = meta.get("agent")
            agent_sid = meta.get("agent_session_id")
            if agent:
                mappings = self._read_agent_sessions()
                key = self._agent_session_key(agent, agent_sid)
                mappings[key] = session_id
                self._write_agent_sessions(mappings)
                
            return {
                "status": "resumed",
                "session_id": session_id,
                "agent_session_id": agent_sid,
                "agent": agent,
                "metadata": meta
            }

    def rewind(self, target: str) -> dict[str, Any]:
        self.init_repo()
        import subprocess
        with file_lock(self.paths.lock_path):
            active = self.get_active_session_id()
            if not active:
                raise MachError("No active session to rewind within.")
                
            try:
                subprocess.check_call(
                    ["git", "restore", "--source", target, "--", "."],
                    cwd=str(self.paths.repo_root),
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError:
                raise MachError(f"Failed to rewind working directory to {target} (is it a valid commit/branch?)")
                
            payload = self._record_step_for_session_unlocked(active, {
                "type": "system_action",
                "content": f"User rewound workspace state to {target}",
                "risk_level": "none",
            })
            return {"status": "rewound", "target": target, "step_recorded": payload}

    def clean(self, max_days: int = 7) -> dict[str, Any]:
        self.init_repo()
        import shutil
        with file_lock(self.paths.lock_path):
            active = self.get_active_session_id()
            cutoff = int(time()) - (max_days * 86400)
            cleaned = []
            
            with connect(self.paths.db_path) as conn:
                rows = conn.execute(
                    "SELECT id FROM sessions WHERE status != 'active' AND started_at < ? AND post_commit IS NULL",
                    (cutoff,)
                ).fetchall()
                
                for r in rows:
                    sid = r["id"]
                    if sid == active:
                        continue
                    sdir = self.paths.sessions_dir / sid
                    if sdir.exists():
                        shutil.rmtree(sdir)
                    conn.execute("DELETE FROM risk_flags WHERE step_id IN (SELECT id FROM steps WHERE session_id=?)", (sid,))
                    conn.execute("DELETE FROM file_changes WHERE step_id IN (SELECT id FROM steps WHERE session_id=?)", (sid,))
                    conn.execute("DELETE FROM tools WHERE step_id IN (SELECT id FROM steps WHERE session_id=?)", (sid,))
                    conn.execute("DELETE FROM steps WHERE session_id=?", (sid,))
                    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
                    cleaned.append(sid)
            return {"cleaned": len(cleaned), "session_ids": cleaned}

    def on_commit(self) -> dict[str, Any] | None:
        config = self.read_config()
        if not config.get("commit_closes_session", False):
            return None
        active = self.get_active_session_id()
        if not active:
            return None
        with file_lock(self.paths.lock_path):
            return self._end_session_unlocked(active)

    def read_config(self) -> dict[str, Any]:
        self.init_repo()
        return merge_config(read_json(self.paths.config_path))

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            current = merge_config(read_json(self.paths.config_path))
            current.update(updates)
            self._write_config(current)
            return current

    def fsck(self) -> dict[str, Any]:
        self.init_repo()
        with file_lock(self.paths.lock_path):
            verification = []
            if self.get_config().get("db_enabled", True):
                reset_db(self.paths.db_path)

            rebuilt_sessions = 0
            rebuilt_steps = 0
            rebuilt_risk_flags = 0

            for session_id in self._session_ids():
                result = self.verify_session(session_id)
                verification.append(result)

                session_dir = self.paths.sessions_dir / session_id
                meta = read_json(session_dir / "meta.json")
                steps = read_jsonl(session_dir / "steps.jsonl")
                risk_count = sum(len(step.get("risk_flags", [])) for step in steps)

                self._upsert_session_index(
                    meta,
                    step_count=len(steps),
                    risk_count=risk_count,
                )
                for step in steps:
                    self._insert_step(step)

                rebuilt_sessions += 1
                rebuilt_steps += len(steps)
                rebuilt_risk_flags += risk_count

            active = self.get_active_session_id()
            if active and not (self.paths.sessions_dir / active).exists():
                self.paths.head_path.write_text("", encoding="utf-8")
                active = None

            return {
                "ok": all(item["valid"] for item in verification),
                "rebuilt_db": str(self.paths.db_path),
                "sessions_rebuilt": rebuilt_sessions,
                "steps_rebuilt": rebuilt_steps,
                "risk_flags_rebuilt": rebuilt_risk_flags,
                "active_session": active,
                "verification": verification,
            }

    def read_session_meta(self, session_id: str) -> dict[str, Any]:
        return read_json(self.paths.sessions_dir / session_id / "meta.json")

    def _write_config(self, config: dict[str, Any]) -> None:
        write_json(self.paths.config_path, config)

    def _write_session_meta(self, meta: dict[str, Any]) -> None:
        write_json(self.paths.sessions_dir / meta["id"] / "meta.json", meta)

    def _read_agent_sessions(self) -> dict[str, str]:
        return read_json(self.paths.agent_sessions_path)

    def _write_agent_sessions(self, mappings: dict[str, str]) -> None:
        write_json(self.paths.agent_sessions_path, mappings)

    @staticmethod
    def _agent_session_key(agent: str, source_session_id: str | None) -> str:
        return f"{agent}:{source_session_id or 'default'}"

    def _ensure_agent_session_unlocked(
        self,
        agent: str,
        source_session_id: str | None = None,
        task_desc: str | None = None,
    ) -> str:
        mappings = self._read_agent_sessions()
        key = self._agent_session_key(agent, source_session_id)
        session_id = mappings.get(key)
        if session_id and (self.paths.sessions_dir / session_id / "meta.json").exists():
            meta = self.read_session_meta(session_id)
            if meta.get("status") == "active":
                self.paths.head_path.write_text(session_id, encoding="utf-8")
                return session_id

        meta = self._create_session_unlocked(agent=agent, task_desc=task_desc, agent_session_id=source_session_id)
        mappings[key] = meta["id"]
        self._write_agent_sessions(mappings)
        return meta["id"]

    def _write_blob(self, content_hash: str, content: str) -> None:
        if not content or not content_hash:
            return
        blob_path = self.paths.blobs_dir / content_hash[:2] / content_hash
        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path.write_text(content, encoding="utf-8")

    def _read_blob(self, content_hash: str) -> str | None:
        if not content_hash:
            return None
        blob_path = self.paths.blobs_dir / content_hash[:2] / content_hash
        if blob_path.exists():
            return blob_path.read_text(encoding="utf-8")
        return None

    def _drop_agent_session_mapping_for_session(self, session_id: str) -> None:
        mappings = self._read_agent_sessions()
        updated = {
            key: value
            for key, value in mappings.items()
            if value != session_id
        }
        if updated != mappings:
            self._write_agent_sessions(updated)

    def _record_step_for_session_unlocked(self, session_id: str, step_dict: dict[str, Any]) -> dict[str, Any]:
        meta = self.read_session_meta(session_id)
        session_dir = self.paths.sessions_dir / session_id
        steps_path = session_dir / "steps.jsonl"
        merkle_path = session_dir / "merkle.sig"

        existing_steps = read_jsonl(steps_path)
        prev_step_id = existing_steps[-1]["id"] if existing_steps else None
        step_num = len(existing_steps) + 1

        config = self.read_config()
        store_content = config.get("store_content", ["input"])

        payload = dict(step_dict)
        payload.setdefault("id", f"step_{uuid.uuid4().hex}")
        payload["session_id"] = session_id
        payload["step_num"] = step_num
        payload.setdefault("ts", int(time()))
        payload.setdefault("type", "output")
        payload.setdefault("content", "")
        payload["content_hash"] = hash_payload({"content": payload["content"]})
        
        step_type = payload["type"]
        raw_content = payload["content"]
        
        if step_type != "system_action" and step_type not in store_content:
            payload["content"] = None
        elif step_type != "system_action":
            # Save the raw content to the blob store and clear from the payload
            if raw_content:
                self._write_blob(payload["content_hash"], raw_content)
            payload["content"] = None

        payload.setdefault("caused_by", [prev_step_id] if prev_step_id else [])
        payload.setdefault("risk_level", "none")

        tool_payload = payload.get("tool")
        if tool_payload:
            tool_payload = dict(tool_payload)
            raw_tool_content = tool_payload.get("content", "")
            tool_payload["content_hash"] = hash_payload({"content": raw_tool_content})
            if "tool" not in store_content:
                tool_payload["content"] = None
            else:
                if raw_tool_content:
                    self._write_blob(tool_payload["content_hash"], raw_tool_content)
                tool_payload["content"] = None
            payload["tool"] = tool_payload

        append_jsonl(steps_path, payload)

        merkle = read_json(merkle_path)
        root = chain_hash(payload, merkle.get("root"))
        merkle["root"] = root
        merkle["steps"] = step_num
        write_json(merkle_path, merkle)

        self.paths.head_path.write_text(session_id, encoding="utf-8")
        self._insert_step(payload)
        self._upsert_session_index(
            meta,
            step_count=step_num,
            risk_count=self._risk_count(session_id),
        )
        return payload

    def _session_ids(self) -> list[str]:
        if not self.paths.sessions_dir.exists():
            return []
        return [
            session_dir.name
            for session_dir in sorted(self.paths.sessions_dir.iterdir())
            if session_dir.is_dir()
        ]

    def _upsert_session_index(self, meta: dict[str, Any], step_count: int, risk_count: int) -> None:
        if not self.get_config().get("db_enabled", True):
            return
        with connect(self.paths.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, started_at, ended_at, agent, branch, pre_commit, post_commit,
                  step_count, risk_count, synced_at, agent_session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  started_at=excluded.started_at,
                  ended_at=excluded.ended_at,
                  agent=excluded.agent,
                  branch=excluded.branch,
                  pre_commit=excluded.pre_commit,
                  post_commit=excluded.post_commit,
                  step_count=excluded.step_count,
                  risk_count=excluded.risk_count,
                  synced_at=excluded.synced_at,
                  agent_session_id=excluded.agent_session_id
                """,
                (
                    meta["id"],
                    meta["started_at"],
                    meta["ended_at"],
                    meta["agent"],
                    meta["branch"],
                    meta["pre_commit"],
                    meta["post_commit"],
                    step_count,
                    risk_count,
                    None,
                    meta.get("agent_session_id"),
                ),
            )

    def _insert_step(self, payload: dict[str, Any]) -> None:
        if not self.get_config().get("db_enabled", True):
            return
        with connect(self.paths.db_path) as conn:
            conn.execute(
                """
                INSERT INTO steps (
                  id, session_id, step_num, ts, type, content, content_hash, caused_by, risk_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["session_id"],
                    payload["step_num"],
                    payload["ts"],
                    payload["type"],
                    payload["content"],
                    payload["content_hash"],
                    canonical_json(payload.get("caused_by", [])),
                    payload["risk_level"],
                ),
            )

            tool_payload = payload.get("tool")
            if tool_payload:
                conn.execute(
                    """
                    INSERT INTO tools (id, step_id, name, category, content, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"tool_{uuid.uuid4().hex}",
                        payload["id"],
                        tool_payload.get("name"),
                        tool_payload.get("category"),
                        tool_payload.get("content"),
                        tool_payload.get("content_hash"),
                    ),
                )

            for change in payload.get("file_changes", []):
                conn.execute(
                    """
                    INSERT INTO file_changes (
                      id, step_id, file_path, action, before_blob, after_blob,
                      lines_added, lines_removed, hunks, sensitivity
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"fc_{uuid.uuid4().hex}",
                        payload["id"],
                        change.get("file_path"),
                        change.get("action"),
                        change.get("before_blob"),
                        change.get("after_blob"),
                        change.get("lines_added"),
                        change.get("lines_removed"),
                        canonical_json(change.get("hunks", [])),
                        change.get("sensitivity", "none"),
                    ),
                )

            for flag in payload.get("risk_flags", []):
                conn.execute(
                    """
                    INSERT INTO risk_flags (id, step_id, rule_id, severity, explanation, resolved)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"rf_{uuid.uuid4().hex}",
                        payload["id"],
                        flag.get("rule_id"),
                        flag.get("severity"),
                        flag.get("explanation"),
                        1 if flag.get("resolved") else 0,
                    ),
                )

    def _step_count(self, session_id: str) -> int:
        try:
            with connect(self.paths.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS count FROM steps WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return int(row["count"]) if row else 0
        except Exception:
            return 0

    def _risk_count(self, session_id: str) -> int:
        try:
            with connect(self.paths.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM risk_flags rf
                    JOIN steps s ON s.id = rf.step_id
                    WHERE s.session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
            return int(row["count"]) if row else 0
        except Exception:
            return 0
