"""
mach.tui — Premium interactive terminal dashboard.

Native terminal aesthetics.
Split-screen: sessions (left) | timeline (right). Enter → step detail modal.
"""
from __future__ import annotations

import re
import time as _time
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label, ListItem, ListView, Static, Rule
from rich.text import Text
from rich.console import Console
from rich.segment import Segment

from mach.session import SessionStore


# ══════════════════════════════════════════════════════════
#  Constants & helpers
# ══════════════════════════════════════════════════════════

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\\033\[[0-9;]*[A-Za-z]")


def _strip(text: str) -> str:
    return _ANSI_RE.sub("", str(text))


def _rel(ts: int) -> str:
    if not ts:
        return "?"
    d = max(0, int(_time.time()) - ts)
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


def _abs_ts(ts: int) -> str:
    if not ts:
        return ""
    return _time.strftime("%b %d  %H:%M", _time.localtime(ts))


def _coalesce(steps: list[dict]) -> list[dict]:
    out: list[dict] = []
    for step in steps:
        stype = step.get("type", "unknown")
        tool = step.get("tool")
        content = step.get("content", "")
        if tool:
            name = tool.get("name")
            out.append(dict(
                id=step["id"], ts=step.get("ts", 0), type="tool",
                name=name, category=tool.get("category", "exec"),
                content=_strip(tool.get("content") or ""),
                file_changes=step.get("file_changes"), count=1,
            ))
            continue
        if stype == "reasoning" and out and out[-1]["type"] == "reasoning":
            out[-1]["content"] = (out[-1].get("content") or "") + (content or "")
            out[-1].update(id=step["id"], ts=step.get("ts", 0))
        else:
            out.append(dict(id=step["id"], ts=step.get("ts", 0),
                            type=stype, content=_strip(content or "")))
    return out


# visual config using native terminal colors
STEP_ICON = {
    "input":         ("▸", "bold cyan"),
    "reasoning":     ("◆", "bold magenta"),
    "tool":          ("⬡", "bold yellow"),
    "output":        ("◀", "bold green"),
    "system_action": ("·", "dim"),
}
TOOL_CAT_ICON = {"write": "✎", "read": "≡", "search": "⌕", "exec": "❯"}
AGENT_COLOR = {
    "gemini":  "cyan",
    "claude":  "yellow",
    "codex":   "green",
    "copilot": "magenta",
    "cursor":  "blue",
}


# ══════════════════════════════════════════════════════════
#  Step Detail Modal
# ══════════════════════════════════════════════════════════

class StepDetail(ModalScreen[None]):
    BINDINGS = [Binding("escape,q", "dismiss", "Close")]

    DEFAULT_CSS = """
    StepDetail {
        align: center middle;
        background: $background 70%;
    }
    #modal-outer {
        width: 85%;
        height: 82%;
        background: $surface;
        border: round $primary;
        padding: 0;
    }
    #modal-header {
        height: auto;
        background: $panel;
        border-bottom: solid $primary;
        padding: 1 2;
    }
    #modal-body {
        height: 1fr;
        padding: 1 2;
    }
    #modal-footer-bar {
        height: 1;
        background: $panel;
        border-top: solid $primary;
        padding: 0 2;
        content-align: left middle;
    }
    """

    def __init__(self, step: dict, agent: str) -> None:
        super().__init__()
        self.step = step
        self.agent = agent

    def compose(self) -> ComposeResult:
        s = self.step
        stype = s.get("type", "unknown")
        icon, ic = STEP_ICON.get(stype, ("·", "dim"))
        label = stype.upper()
        ts = s.get("ts", 0)
        acol = AGENT_COLOR.get(self.agent.lower(), "white")

        with Vertical(id="modal-outer"):
            # ── Header ──
            with Container(id="modal-header"):
                h = Text()
                h.append(f"  {icon} ", style=ic)
                h.append(f"{label}", style=f"bold {ic.split()[-1] if ' ' in ic else ic}")
                h.append("   ", style="dim")
                h.append("step:", style="dim")
                h.append(f" {s.get('id', '?')}", style="blue")
                h.append("   agent:", style="dim")
                h.append(f" {self.agent}", style=f"bold {acol}")
                if ts:
                    h.append(f"   {_abs_ts(ts)}", style="dim")
                    h.append(f"  ({_rel(ts)})", style="dim")
                yield Static(h)

                if stype == "tool":
                    cat = s.get("category", "exec")
                    ci = TOOL_CAT_ICON.get(cat, "·")
                    count = s.get("count", 1)
                    t2 = Text()
                    t2.append(f"  {ci} ", style="yellow")
                    t2.append(s.get("name", "?"), style="bold yellow")
                    t2.append(f"  [{cat}]", style="dim")
                    if count > 1:
                        t2.append(f"  ×{count} calls", style="dim yellow")
                    yield Static(t2)

            # ── Body ──
            with VerticalScroll(id="modal-body"):
                content = _strip(s.get("content") or "").strip()
                if content:
                    yield Static(Text(content))
                else:
                    yield Static(Text("  (no content stored — privacy policy redacted)", style="dim italic"))

                fc = s.get("file_changes")
                if fc:
                    yield Static(Text(""))
                    sep = Text()
                    sep.append("  ── ", style="dim")
                    sep.append("File Changes", style="bold")
                    sep.append(f"  ({len(fc)} file{'s' if len(fc) != 1 else ''})", style="dim")
                    yield Static(sep)
                    yield Static(Text(""))
                    for ch in fc:
                        action = ch.get("action", "write")
                        fp = ch.get("file_path", "?")
                        added = ch.get("lines_added", 0) or 0
                        removed = ch.get("lines_removed", 0) or 0
                        astyle = {"write": "green", "read": "cyan",
                                  "delete": "red"}.get(action, "dim")
                        line = Text()
                        line.append(f"  {action.upper():<6}", style=f"bold {astyle}")
                        line.append(f"  {fp}", style="white")
                        if added or removed:
                            line.append(f"  +{added}", style="green")
                            line.append(f"  -{removed}", style="red")
                        yield Static(line)
                        for h in ch.get("hunks", []):
                            hs, he = h.get("from", 0), h.get("to", 0)
                            hl = Text()
                            hl.append(f"        @@ -{hs},{max(1,he-hs+1)} +{hs},{max(1,he-hs+1)} @@",
                                      style="cyan")
                            yield Static(hl)

            # ── Footer ──
            foot = Text()
            foot.append("  ESC ", style="bold yellow")
            foot.append("close", style="dim")
            yield Static(foot, id="modal-footer-bar")


# ══════════════════════════════════════════════════════════
#  Main App
# ══════════════════════════════════════════════════════════

class MachApp(App):
    TITLE = "mach"
    SUB_TITLE = "execution ledger"

    CSS = """
    /* ── Global ── */
    Screen {
        background: transparent;
    }

    /* ── Top banner ── */
    #banner {
        dock: top;
        height: 3;
        background: transparent;
        border-bottom: solid $primary;
        padding: 0 3;
        content-align: left middle;
    }

    /* ── Layout ── */
    #split {
        height: 1fr;
    }

    /* ── Session pane ── */
    #session-pane {
        width: 36;
        min-width: 28;
        height: 1fr;
        border-right: solid $primary;
        background: transparent;
    }
    #session-pane-title {
        height: 2;
        background: transparent;
        border-bottom: solid $primary;
        padding: 0 2;
        content-align: left middle;
    }
    ListView {
        height: 1fr;
        background: transparent;
        padding: 0;
        border: none;
    }
    ListView:focus {
        border: none;
    }
    ListItem {
        height: 5;
        padding: 1 2;
        border-bottom: solid $surface-lighten-1;
        background: transparent;
    }
    ListItem.--highlight {
        background: $surface;
        border-left: thick $accent;
    }
    ListItem:hover {
        background: $surface;
    }

    /* ── Steps pane ── */
    #steps-pane {
        width: 1fr;
        height: 1fr;
        background: transparent;
    }
    #steps-pane-title {
        height: 2;
        background: transparent;
        border-bottom: solid $primary;
        padding: 0 2;
        content-align: left middle;
    }
    DataTable {
        height: 1fr;
        background: transparent;
    }
    DataTable > .datatable--header {
        background: transparent;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: $primary;
    }
    DataTable > .datatable--even-row {
        background: transparent;
    }

    /* ── Footer ── */
    Footer {
        background: transparent;
        border-top: solid $primary;
        height: 1;
    }
    Footer > .footer--key {
        background: $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("tab,right", "focus_steps", "→ Steps", show=True),
        Binding("escape,left", "focus_sessions", "← Sessions", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def __init__(self, store: SessionStore) -> None:
        super().__init__()
        self.store = store
        self.sessions: list[dict] = []
        self.steps: list[dict] = []
        self.agent = "unknown"

    def compose(self) -> ComposeResult:
        # Banner
        banner = Text()
        banner.append("⬡ ", style="bold blue")
        banner.append("MACH", style="bold")
        banner.append("  execution ledger", style="dim")
        banner.append("   ·   ", style="dim")
        banner.append("audit-grade AI tracing", style="dim")
        yield Static(banner, id="banner")

        with Horizontal(id="split"):
            # Left: sessions
            with Vertical(id="session-pane"):
                yield Static(self._sessions_title(), id="session-pane-title")
                yield ListView(id="session-list")

            # Right: steps
            with Vertical(id="steps-pane"):
                yield Static(self._steps_title(), id="steps-pane-title")
                yield DataTable(id="steps-table", cursor_type="row",
                                zebra_stripes=True, show_cursor=True)

        yield Footer()

    def _sessions_title(self) -> Text:
        t = Text()
        t.append(" Sessions", style="bold blue")
        if self.sessions:
            t.append(f"  {len(self.sessions)}", style="dim yellow")
        return t

    def _steps_title(self, label: str = "Timeline", count: int = 0,
                     sid: str = "") -> Text:
        t = Text()
        t.append(" Timeline", style="bold blue")
        if sid:
            t.append(f"  {sid}", style="dim")
        if count:
            t.append(f"  {count} steps", style="dim yellow")
        return t

    def on_mount(self) -> None:
        tt = self.query_one("#steps-table", DataTable)
        tt.add_columns(" ", "Type", "Detail", "Time")
        self._load_sessions()
        self.query_one("#session-list", ListView).focus()

    # ── Session list ──

    def _load_sessions(self) -> None:
        self.sessions = self.store.list_sessions()
        lv = self.query_one("#session-list", ListView)
        lv.clear()
        for s in self.sessions:
            lv.append(self._make_session_item(s))
        self.query_one("#session-pane-title", Static).update(self._sessions_title())

    def _make_session_item(self, s: dict) -> ListItem:
        sid = str(s.get("id", "")).replace("ses_", "")[:10]
        agent = str(s.get("agent", "?"))
        branch = str(s.get("branch", "?"))
        status = s.get("status") or ("active" if not s.get("ended_at") else "ended")
        n_steps = s.get("step_count", 0)
        started = s.get("started_at", 0)
        is_active = status == "active"
        acol = AGENT_COLOR.get(agent.lower(), "white")

        # Line 1: status bullet + short ID
        line1 = Text()
        line1.append("● " if is_active else "○ ",
                      style="bold green" if is_active else "dim")
        line1.append(sid, style="bold")

        # Line 2: agent + branch
        line2 = Text()
        line2.append(agent, style=f"bold {acol}")
        line2.append("  on ", style="dim")
        line2.append(branch, style="cyan")

        # Line 3: steps + time
        line3 = Text()
        line3.append(f"{n_steps} steps", style="dim")
        line3.append("  ·  ", style="dim")
        line3.append(_rel(started), style="dim")

        content = Text.assemble(line1, "\n", line2, "\n", line3)
        return ListItem(Static(content))

    # ── Steps table ──

    def _load_steps(self, session: dict) -> None:
        sid = session.get("id", "")
        self.agent = str(session.get("agent", "unknown"))
        try:
            data = self.store.show_session(sid)
            self.steps = _coalesce(data["steps"])
        except Exception:
            self.steps = []

        tt = self.query_one("#steps-table", DataTable)
        tt.clear()

        short_id = sid.replace("ses_", "")[:12]
        self.query_one("#steps-pane-title", Static).update(
            self._steps_title(sid=short_id, count=len(self.steps))
        )

        for step in self.steps:
            stype = step.get("type", "unknown")
            icon, ic = STEP_ICON.get(stype, ("·", "dim"))
            ts = step.get("ts", 0)

            icon_cell = Text(icon, style=ic)

            label_cell = Text(stype.upper(), style=ic + " bold" if "bold" not in ic else ic)

            if stype == "tool":
                count = step.get("count", 1)
                cat = step.get("category", "exec")
                ci = TOOL_CAT_ICON.get(cat, "·")
                detail = Text()
                detail.append(f"{ci} ", style="yellow")
                detail.append(step.get("name", "?"), style="bold yellow")
                tool_content = _strip(step.get("content") or "").strip().replace("\n", " ")
                if tool_content:
                    detail.append("  ", style="dim")
                    detail.append(tool_content[:70] + "…" if len(tool_content) > 70
                                  else tool_content, style="dim")
                if count > 1:
                    detail.append(f"  ×{count}", style="bold yellow")
            else:
                raw = _strip(step.get("content") or "").strip().replace("\n", " ")
                if not raw:
                    detail = Text("(redacted)", style="dim italic")
                else:
                    detail = Text(raw[:110] + "…" if len(raw) > 110 else raw)

            ts_cell = Text(_abs_ts(ts), style="dim") if ts else Text("")
            tt.add_row(icon_cell, label_cell, detail, ts_cell)

    # ── Events ──

    @on(ListView.Highlighted, "#session-list")
    def on_session_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self.sessions):
            self._load_steps(self.sessions[idx])

    @on(ListView.Selected, "#session-list")
    def on_session_selected(self, event: ListView.Selected) -> None:
        # Move focus to steps table
        self.query_one("#steps-table", DataTable).focus()

    @on(DataTable.RowSelected, "#steps-table")
    def on_step_selected(self, event: DataTable.RowSelected) -> None:
        row = event.cursor_row
        if row is not None and 0 <= row < len(self.steps):
            self.push_screen(StepDetail(self.steps[row], self.agent))

    # ── Actions ──

    def action_focus_steps(self) -> None:
        self.query_one("#steps-table", DataTable).focus()

    def action_focus_sessions(self) -> None:
        self.query_one("#session-list", ListView).focus()

    def action_refresh(self) -> None:
        self._load_sessions()
        self.notify("Sessions refreshed", severity="information", timeout=2)


def run_tui(store: SessionStore) -> None:
    MachApp(store).run()
