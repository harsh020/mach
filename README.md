# Mach

Mach is a local-first, Git-adjacent execution logging system for AI agents.

This starter implements the first core slice from the spec:

- `mach init`
- `mach enable`
- `mach disable`
- `mach config show|set`
- `mach configure`
- `mach session start`
- `mach session end`
- `mach log`
- `mach show`
- `mach verify`
- `mach fsck`
- `mach on-commit`
- automatic repo tracking after `mach init`
- AI activity ingestion for `input`, `reasoning`, `tool`, and `output`
- agent-scoped sessions keyed by agent + external session id
- `mach ingest event|end|process`
- `mach hooks install|uninstall|status`
- automatic hook installation for supported agents on `mach init`
- `mach track start|stop|status|scan`
- Python SDK entrypoint: `mach.record_step(step_dict)`

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
mach init
mach hooks status
mach config show
mach configure --add-agent gemini --remove-agent cursor --refresh-hooks --apply
mach ingest event --agent codex --source-session-id turn-42 --type input --content "fix auth bug"
mach ingest process
mach track status
mach log
mach show
mach verify
mach fsck
```

## Hook Support

- `claude`: project-local hooks installed into `.claude/settings.local.json`
- `copilot`: repository hooks installed into `.github/hooks/mach.json`
- `gemini`: project-local hooks installed into `.gemini/settings.json`
- `codex`: global hooks installed into `~/.codex/hooks.json` and `~/.codex/config.toml`
- `cursor`: no full prompt/tool hook surface installed; Mach reports this as `status-webhook-only`

## Setup Model

- `mach init`: bootstrap `.mach`, persist default config, install hooks for configured agents, and start the tracker
- `mach enable`: turn the integration back on using the stored config
- `mach disable`: uninstall configured hooks and stop the tracker
- `mach config set --hook-agents claude,codex,copilot,gemini`: choose which agents Mach should manage
- `mach configure --add-agent claude --remove-agent cursor --refresh-hooks --apply`: high-level setup flow to update config and immediately reconcile hooks/tracking

## Notes

- JSONL under `.mach/sessions/` is the source of truth.
- SQLite in `.mach/index.db` is a derived index.
- `mach fsck` rebuilds the SQLite index from the session logs.
- Git integration is best-effort and works even before the repo is initialized.
- `commit_closes_session` and idle timeout are off by default.
- `mach init` prepares tracker state and starts a background tracker by default.
- Mach can ingest AI-native events directly through `.mach/inbox/*.jsonl` or the `mach ingest ...` CLI.
- The tracker processes queued AI events continuously after `mach init`.
- `mach init` also installs Mach-managed hooks for supported agents so their prompt/tool/session events can flow into Mach automatically.
- Mach now stores selected managed agents in config, which is closer to Entire’s `enable/configure/disable` workflow.
- `mach config set` is the low-level config editor; `mach configure` is the higher-level operational command.
- Repo observation is now secondary evidence: file creates, writes, deletes, and Git HEAD/branch changes are logged separately under `workspace-observer`.
- Hook fidelity depends on the upstream agent surface. Claude, Copilot, and Gemini expose rich hook events; Codex is narrower; Cursor currently exposes background-agent status webhooks and MCP rather than full local prompt/tool hooks.
