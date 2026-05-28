from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              started_at INTEGER,
              ended_at INTEGER,
              agent TEXT,
              agent_session_id TEXT,
              branch TEXT,
              pre_commit TEXT,
              post_commit TEXT,
              step_count INTEGER DEFAULT 0,
              risk_count INTEGER DEFAULT 0,
              forked_from TEXT,
              synced_at INTEGER,
              head_step_id TEXT
            );

            CREATE TABLE IF NOT EXISTS steps (
              id TEXT PRIMARY KEY,
              session_id TEXT,
              step_num INTEGER,
              ts INTEGER,
              type TEXT,
              content TEXT,
              content_hash TEXT,
              caused_by TEXT,
              risk_level TEXT,
              parent_step_id TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS tools (
              id TEXT PRIMARY KEY,
              step_id TEXT,
              name TEXT,
              category TEXT,
              content TEXT,
              content_hash TEXT,
              FOREIGN KEY(step_id) REFERENCES steps(id)
            );

            CREATE TABLE IF NOT EXISTS file_changes (
              id TEXT PRIMARY KEY,
              step_id TEXT,
              file_path TEXT,
              action TEXT,
              before_blob TEXT,
              after_blob TEXT,
              lines_added INTEGER,
              lines_removed INTEGER,
              hunks TEXT,
              sensitivity TEXT,
              FOREIGN KEY(step_id) REFERENCES steps(id)
            );

            CREATE TABLE IF NOT EXISTS risk_flags (
              id TEXT PRIMARY KEY,
              step_id TEXT,
              rule_id TEXT,
              severity TEXT,
              explanation TEXT,
              resolved INTEGER,
              FOREIGN KEY(step_id) REFERENCES steps(id)
            );
            """
        )
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN agent_session_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN forked_from TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN head_step_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE steps ADD COLUMN parent_step_id TEXT")
        except sqlite3.OperationalError:
            pass


def reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
