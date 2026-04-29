<div align="center">

# 🚀 Mach

**Local-first, Git-adjacent execution logging system for AI agents.**

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

## 📖 Overview

Mach is a comprehensive, local-first execution tracking system designed specifically for AI agents. It seamlessly captures inputs, reasoning, tool usage, and outputs across various AI assistants. By integrating closely with your Git workflow, Mach provides a verifiable, searchable, and structured history of AI interactions directly within your repositories.

## ✨ Key Features

- **Comprehensive Activity Tracking:** Logs AI activity across the entire lifecycle: `input`, `reasoning`, `tool`, and `output`.
- **Git-Adjacent Workflow:** Works alongside your Git repository, logging workspace changes (creates, writes, deletes, branch changes) as secondary evidence.
- **Agent-Scoped Sessions:** Organizes execution logs logically by agent and external session IDs.
- **Seamless Integrations:** Automatic hook installation for supported AI agents (Claude, Copilot, Gemini, Codex).
- **Robust Storage Architecture:** Uses JSONL as the uncorruptible source of truth, backed by a derived SQLite index (`.mach/index.db`) for fast querying.
- **Continuous Ingestion:** Includes a background tracker that continuously processes queued AI events.
- **Python SDK:** Easily instrument your own scripts via `mach.record_step(step_dict)`.

## 🚀 Installation

Mach requires Python 3.9 or higher. To install, clone the repository and install it in a virtual environment:

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install Mach
pip install -e .
```

## 🏁 Quick Start

Initialize Mach in your current repository and explore its capabilities:

```bash
# Bootstrap .mach, choose agent hooks, and start the tracker
mach init

# Scripted setup without the interactive selector
mach init --hook-agents claude,codex,gemini

# Check the status of installed hooks
mach hooks status

# View current configuration
mach config show

# Configure specific agents and apply tracking changes
mach configure --add-agent gemini --remove-agent cursor --refresh-hooks --apply

# Manually ingest an event
mach ingest event --agent codex --source-session-id turn-42 --type input --content "fix auth bug"
mach ingest process

# Check tracker status and view the log
mach track status
mach log
```

## 🔌 Hook Support

Mach supports integrating with various popular AI agents to automatically capture execution context:

- **Claude:** Project-local hooks installed into `.claude/settings.local.json`
- **Copilot:** Repository hooks installed into `.github/hooks/mach.json`
- **Gemini:** Project-local hooks installed into `.gemini/settings.json`
- **Codex:** Global hooks installed into `~/.codex/hooks.json` and `~/.codex/config.toml`
- **Cursor:** Exposes background-agent status webhooks and MCP (*reports as `status-webhook-only`*)

## 💻 Command Reference

### Setup & Configuration
- `mach init`: Bootstrap `.mach`, choose agent hooks with an interactive selector, and start tracking.
- `mach enable`: Turn the integration back on using stored configuration.
- `mach disable`: Uninstall configured hooks and stop the tracker.
- `mach config show|set`: View or edit low-level configurations.
- `mach configure`: High-level operational command to update config and reconcile hooks/tracking.

### Session Management
- `mach session start`: Start a new execution session.
- `mach session end`: End the current execution session.

### Logging & Verification
- `mach log`: View execution logs in an interactive TUI or classic paginated view.
- `mach show`: Display details of specific execution steps.
- `mach verify`: Verify the cryptographic integrity of the logs.
- `mach fsck`: Rebuild the SQLite index from the JSONL session logs.

### Tracking & Ingestion
- `mach track start|stop|status|scan`: Manage the background tracker process.
- `mach ingest event|end|process`: Interface directly with the inbox queue to record raw events.
- `mach hooks install|uninstall|status`: Manage integration hooks for supported agents.

## 🏗️ Architecture Notes

- **Source of Truth:** All events are durably appended to JSONL files under `.mach/sessions/`.
- **Indexing:** The SQLite database at `.mach/index.db` is purely a derived index and can be rebuilt at any time via `mach fsck`.
- **Asynchronous Ingestion:** AI-native events are written to `.mach/inbox/*.jsonl`. The background tracker continuously processes these into the structured session log.
- **Git Independence:** Git integration works best-effort, even before a repository is fully initialized.
