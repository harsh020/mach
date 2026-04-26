"""
mach.tui — Premium interactive terminal dashboard.

Dark, information-dense, git-native aesthetic.
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
            if out and out[-1]["type"] == "tool" and out[-1].get("name") == name:
                out[-1].update(id=step["id"], ts=step.get("ts", 0),
                               count=out[-1].get("count", 1) + 1)
            else:
                out.append(dict(
                    id=step["id"], ts=step.get("ts", 0), type="tool",
                    name=name, category=tool.get("category", "exec"),
                    content=_strip(tool.get("content") or ""),
                    file_changes=step.get("file_changes"), count=1,
                ))
            continue
        if out and out[-1]["type"] == stype and stype != "tool":
            out[-1]["content"] = (out[-1].get("content") or "") + (content or "")
            out[-1].update(id=step["id"], ts=step.get("ts", 0))
        else:
            out.append(dict(id=step["id"], ts=step.get("ts", 0),
                            type=stype, content=_strip(content or "")))
    return out


# visual config
STEP_ICON = {
    "input":         ("▸", "bold #7dcfff"),
    "reasoning":     ("◆", "bold #bb9af7"),
    "tool":          ("⬡", "bold #e0af68"),
    "output":        ("◀", "bold #9ece6a"),
    "system_action": ("·", "dim #565f89"),
}
TOOL_CAT_ICON = {"write": "✎", "read": "≡", "search": "⌕", "exec": "❯"}
AGENT_COLOR = {
    "gemini":  "#4fc3f7",
    "claude":  "#ff9e64",
    "codex":   "#9ece6a",
    "copilot": "#bb9af7",
    "cursor":  "#7aa2f7",
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
        background: #1a1b26;
        border: round #414868;
        padding: 0;
    }
    #modal-header {
        height: auto;
        background: #16161e;
        border-bottom: solid #414868;
        padding: 1 2;
    }
    #modal-body {
        height: 1fr;
        padding: 1 2;
    }
    #modal-footer-bar {
        height: 1;
        background: #16161e;
        border-top: solid #414868;
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
        acol = AGENT_COLOR.get(self.agent.lower(), "#c0caf5")

        with Vertical(id="modal-outer"):
            # ── Header ──
            with Container(id="modal-header"):
                h = Text()
                h.append(f"  {icon} ", style=ic)
                h.append(f"{label}", style=f"bold {ic.split()[-1] if ' ' in ic else ic}")
                h.append("   ", style="dim")
                h.append("step:", style="dim #565f89")
                h.append(f" {s.get('id', '?')}", style="#7aa2f7")
                h.append("   agent:", style="dim #565f89")
                h.append(f" {self.agent}", style=f"bold {acol}")
                if ts:
                    h.append(f"   {_abs_ts(ts)}", style="dim #565f89")
                    h.append(f"  ({_rel(ts)})", style="dim #414868")
                yield Static(h)

                if stype == "tool":
                    cat = s.get("category", "exec")
                    ci = TOOL_CAT_ICON.get(cat, "·")
                    count = s.get("count", 1)
                    t2 = Text()
                    t2.append(f"  {ci} ", style="#e0af68")
                    t2.append(s.get("name", "?"), style="bold #e0af68")
                    t2.append(f"  [{cat}]", style="dim #565f89")
                    if count > 1:
                        t2.append(f"  ×{count} calls", style="dim #ff9e64")
                    yield Static(t2)

            # ── Body ──
            with VerticalScroll(id="modal-body"):
                content = _strip(s.get("content") or "").strip()
                if content:
                    yield Static(Text(content))
                else:
                    yield Static(Text("  (no content stored — privacy policy redacted)", style="dim italic #565f89"))

                fc = s.get("file_changes")
                if fc:
                    yield Static(Text(""))
                    sep = Text()
                    sep.append("  ── ", style="dim #414868")
                    sep.append("File Changes", style="bold #c0caf5")
                    sep.append(f"  ({len(fc)} file{'s' if len(fc) != 1 else ''})", style="dim #565f89")
                    yield Static(sep)
                    yield Static(Text(""))
                    for ch in fc:
                        action = ch.get("action", "write")
                        fp = ch.get("file_path", "?")
                        added = ch.get("lines_added", 0) or 0
                        removed = ch.get("lines_removed", 0) or 0
                        astyle = {"write": "#9ece6a", "read": "#7dcfff",
                                  "delete": "#f7768e"}.get(action, "#565f89")
                        line = Text()
                        line.append(f"  {action.upper():<6}", style=f"bold {astyle}")
                        line.append(f"  {fp}", style="#c0caf5")
                        if added or removed:
                            line.append(f"  +{added}", style="#9ece6a")
                            line.append(f"  -{removed}", style="#f7768e")
                        yield Static(line)
                        for h in ch.get("hunks", []):
                            hs, he = h.get("from", 0), h.get("to", 0)
                            hl = Text()
                            hl.append(f"        @@ -{hs},{max(1,he-hs+1)} +{hs},{max(1,he-hs+1)} @@",
                                      style="#7dcfff")
                            yield Static(hl)

            # ── Footer ──
            foot = Text()
            foot.append("  ESC ", style="bold #e0af68")
            foot.append("close", style="dim #565f89")
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
        background: #13131a;
    }

    /* ── Top banner ── */
    #banner {
        dock: top;
        height: 3;
        background: #16161e;
        border-bottom: solid #414868;
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
        border-right: solid #414868;
        background: #13131a;
    }
    #session-pane-title {
        height: 2;
        background: #16161e;
        border-bottom: solid #414868;
        padding: 0 2;
        content-align: left middle;
    }
    ListView {
        height: 1fr;
        background: #13131a;
        padding: 0;
        border: none;
    }
    ListView:focus {
        border: none;
    }
    ListItem {
        height: 5;
        padding: 1 2;
        border-bottom: solid #1e2030;
        background: #13131a;
    }
    ListItem.--highlight {
        background: #1e2030;
        border-left: thick #7aa2f7;
    }
    ListItem:hover {
        background: #1a1b26;
    }

    /* ── Steps pane ── */
    #steps-pane {
        width: 1fr;
        height: 1fr;
        background: #13131a;
    }
    #steps-pane-title {
        height: 2;
        background: #16161e;
        border-bottom: solid #414868;
        padding: 0 2;
        content-align: left middle;
    }
    DataTable {
        height: 1fr;
        background: #13131a;
        color: #c0caf5;
    }
    DataTable > .datatable--header {
        background: #1e2030;
        color: #7aa2f7;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #283457;
        color: #c0caf5;
    }
    DataTable > .datatable--even-row {
        background: #181825;
    }

    /* ── Footer ── */
    Footer {
        background: #16161e;
        color: #565f89;
        border-top: solid #414868;
        height: 1;
    }
    Footer > .footer--key {
        background: #414868;
        color: #c0caf5;
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
        banner.append("⬡ ", style="bold #7aa2f7")
        banner.append("MACH", style="bold #c0caf5")
        banner.append("  execution ledger", style="dim #565f89")
        banner.append("   ·   ", style="dim #414868")
        banner.append("audit-grade AI tracing", style="dim #565f89")
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
        t.append(" Sessions", style="bold #7aa2f7")
        if self.sessions:
            t.append(f"  {len(self.sessions)}", style="dim #e0af68")
        return t

    def _steps_title(self, label: str = "Timeline", count: int = 0,
                     sid: str = "") -> Text:
        t = Text()
        t.append(" Timeline", style="bold #7aa2f7")
        if sid:
            t.append(f"  {sid}", style="dim #565f89")
        if count:
            t.append(f"  {count} steps", style="dim #e0af68")
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
        acol = AGENT_COLOR.get(agent.lower(), "#c0caf5")

        # Line 1: status bullet + short ID
        line1 = Text()
        line1.append("● " if is_active else "○ ",
                      style="bold #9ece6a" if is_active else "dim #414868")
        line1.append(sid, style="bold #c0caf5")

        # Line 2: agent + branch
        line2 = Text()
        line2.append(agent, style=f"bold {acol}")
        line2.append("  on ", style="dim #565f89")
        line2.append(branch, style="#7dcfff")

        # Line 3: steps + time
        line3 = Text()
        line3.append(f"{n_steps} steps", style="dim #565f89")
        line3.append("  ·  ", style="dim #414868")
        line3.append(_rel(started), style="dim #565f89")

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
                detail.append(f"{ci} ", style="#e0af68")
                detail.append(step.get("name", "?"), style="bold #e0af68")
                tool_content = _strip(step.get("content") or "").strip().replace("\n", " ")
                if tool_content:
                    detail.append("  ", style="dim")
                    detail.append(tool_content[:70] + "…" if len(tool_content) > 70
                                  else tool_content, style="dim #565f89")
                if count > 1:
                    detail.append(f"  ×{count}", style="bold #ff9e64")
            else:
                raw = _strip(step.get("content") or "").strip().replace("\n", " ")
                if not raw:
                    detail = Text("(redacted)", style="dim italic #414868")
                else:
                    detail = Text(raw[:110] + "…" if len(raw) > 110 else raw,
                                  style="#a9b1d6")

            ts_cell = Text(_abs_ts(ts), style="dim #565f89") if ts else Text("")
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
