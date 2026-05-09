from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional, Any

StepType = Literal["input", "reasoning", "tool", "output", "system_action"]
RiskLevel = Literal["none", "low", "medium", "high", "critical"]


@dataclass
class MachPaths:
    repo_root: Path
    mach_dir: Path
    config_path: Path
    head_path: Path
    sessions_dir: Path
    db_path: Path
    pack_dir: Path
    blobs_dir: Path
    lock_path: Path
    agent_sessions_path: Path
    inbox_dir: Path
    ingest_state_path: Path
    tracker_state_path: Path
    tracker_pid_path: Path
    tracker_log_path: Path
    tracker_lock_path: Path

@dataclass
class FileChange:
    action: Literal["write", "read", "delete"]
    file_path: str
    lines_added: int = 0
    lines_removed: int = 0
    hunks: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileChange":
        return cls(
            action=data.get("action", "write"),
            file_path=data.get("file_path", "?"),
            lines_added=data.get("lines_added", 0),
            lines_removed=data.get("lines_removed", 0),
            hunks=data.get("hunks", [])
        )

@dataclass
class ToolCall:
    name: str
    category: str = "exec"
    content_hash: Optional[str] = None
    content: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            name=data.get("name", ""),
            category=data.get("category", "exec"),
            content_hash=data.get("content_hash"),
            content=data.get("content")
        )

@dataclass
class Step:
    id: str
    session_id: str
    step_num: int
    ts: int
    type: StepType
    content_hash: Optional[str] = None
    content: Optional[str] = None
    caused_by: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "none"
    tool: Optional[ToolCall] = None
    file_changes: list[FileChange] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, dropping nulls to keep JSONL clean."""
        d = asdict(self)
        if self.tool is None:
            d.pop("tool", None)
        if not self.file_changes:
            d.pop("file_changes", None)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        tool_data = data.get("tool")
        tool = ToolCall.from_dict(tool_data) if tool_data else None
        
        fc_data = data.get("file_changes", [])
        file_changes = [FileChange.from_dict(fc) for fc in fc_data] if fc_data else []

        return cls(
            id=data.get("id", ""),
            session_id=data.get("session_id", ""),
            step_num=data.get("step_num", 0),
            ts=data.get("ts", 0),
            type=data.get("type", "output"),
            content_hash=data.get("content_hash"),
            content=data.get("content"),
            caused_by=data.get("caused_by", []),
            risk_level=data.get("risk_level", "none"),
            tool=tool,
            file_changes=file_changes
        )

@dataclass
class SessionMeta:
    id: str
    agent: str
    agent_session_id: Optional[str] = None
    task_desc: Optional[str] = None
    started_at: int = 0
    ended_at: Optional[int] = None
    status: Literal["active", "ended"] = "active"
    branch: str = "main"
    pre_commit: Optional[str] = None
    post_commit: Optional[str] = None
    step_count: int = 0
    risk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        return cls(
            id=data.get("id", ""),
            agent=data.get("agent", "unknown"),
            agent_session_id=data.get("agent_session_id"),
            task_desc=data.get("task_desc"),
            started_at=data.get("started_at", 0),
            ended_at=data.get("ended_at"),
            status=data.get("status", "active"),
            branch=data.get("branch", "main"),
            pre_commit=data.get("pre_commit"),
            post_commit=data.get("post_commit"),
            step_count=data.get("step_count", 0),
            risk_count=data.get("risk_count", 0)
        )
