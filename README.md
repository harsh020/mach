<div align="center">

# 🚀 Mach

**Local-first, Git-adjacent execution ledger for AI agents.**

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

## 📖 What is Mach?

Mach is a high-performance execution tracking system for AI agents. It seamlessly intercepts and logs AI reasoning, inputs, tool calls, and outputs. By sitting right beside your Git repository, Mach provides a cryptographically verifiable, searchable, and structured history of *everything* your AI assistants do.

## ✨ Core Architecture

Mach is built for uncompromising speed, durability, and a native developer experience:

- **Git-Style Blob Storage:** Massive AI outputs and prompts are hashed and deduplicated into a native blob store (`.mach/blobs/`). This keeps your core JSONL logs ultra-lightweight and blazingly fast to parse.
- **Lightning TUI & Search:** Drop into a premium, interactive terminal dashboard (`mach log`). Press `/` at any time to execute real-time, instantaneous searches across thousands of AI events and code chunks.
- **Hybrid Indexing (Toggleable):** Mach uses a fast SQLite FTS5 index (`.mach/index.db`) for sub-millisecond queries. Running on a constrained system? Toggle it off via `--db-enabled false` and Mach will gracefully degrade to pure file-system blob traversal, just like Git.
- **Zero-Latency Ingestion:** AI events are fired into an asynchronous inbox. A lightweight background daemon processes them into the ledger, ensuring 0ms latency impact on your actual AI workflows.
- **Seamless Hooks:** Automatically installs intercepts for Claude, Copilot, Gemini, Codex, and Cursor.

## 🚀 Installation

Mach requires Python 3.9+ and is designed to be installed globally via our standalone installer script. It automatically isolates itself so it never conflicts with your system Python.

```bash
# Install Mach globally
curl -fsSL https://raw.githubusercontent.com/harsh020/mach/main/install.sh | bash
```

To completely uninstall Mach (safely preserving your existing repository logs):
```bash
curl -fsSL https://raw.githubusercontent.com/harsh020/mach/main/uninstall.sh | bash
```

## 🏁 Quick Start

Navigate to any codebase and initialize Mach:

```bash
# Bootstrap .mach and launch the interactive agent selector
mach init

# Or bypass the interactive prompt for CI/CD
mach init --hook-agents claude,codex,gemini
```

### The TUI Dashboard
Once Mach is tracking your agents, launch the interactive dashboard:
```bash
mach log
```
* **Navigate:** Use `Arrow Keys` or `Tab` to move between your active AI sessions and the event timeline.
* **Inspect:** Press `Enter` on any step to open a detailed modal showing exact file diffs and raw content.
* **Search:** Press `/` to instantly filter the timeline by tool name, AI reasoning, or file modifications.

## ⚙️ Configuration

You can fully customize how Mach behaves by viewing and editing its configuration. Configurations are stored locally in `.mach/config`.

**To view all current configurations:**
```bash
mach config show
```

**To change a configuration:**
You can use `mach config set <key> <value>` for low-level overrides, or use the safer `mach configure` command for high-level setup.
```bash
# Example: Disable the SQLite database indexing
mach config set db_enabled false

# Example: Disable the TUI and revert to classic terminal logs
mach config set use_tui false
```

### Configurable Keys:
| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master switch to enable/disable Mach tracking. |
| `auto_session` | `true` | Automatically groups orphan events into active sessions. |
| `auto_tracking` | `true` | Automatically launches the background daemon when needed. |
| `use_tui` | `true` | Uses the interactive Textual TUI for `mach log`. Set to `false` for raw text logs. |
| `db_enabled` | `true` | Enables the SQLite FTS5 database for instant searching. |
| `hook_agents` | `[...]` | List of AI agents to automatically install intercepts for. |
| `ignore_paths` | `[...]` | Directories to ignore when calculating file diffs (e.g., `node_modules`). |
| `poll_interval_sec`| `2` | How often the background daemon checks the inbox. |

## 💻 Command Reference

### Setup & Configuration
- `mach init`: Bootstrap the repository, interactively select hooks, and start the daemon.
- `mach configure`: Re-evaluate your hook settings (e.g. `mach configure --db-enabled false`).
- `mach config show|set`: View or manually override low-level config tokens.
- `mach enable` / `mach disable`: Globally toggle tracking without losing configuration.

### Session & Event Management
- `mach log`: Open the interactive TUI.
- `mach show <session_id>`: Dump raw JSON output of a specific execution timeline.
- `mach verify`: Cryptographically verify the integrity of the JSONL ledger and Blob hashes.
- `mach fsck`: Rebuild the SQLite search index from scratch using the raw Blob store.

### Daemon Controls
- `mach track start|stop|status`: Manage the background ingestion process.
- `mach hooks status`: Check the health and presence of your AI agent intercepts.

---
<div align="center">
<i>Built to make AI execution as verifiable as your code.</i>
</div>
