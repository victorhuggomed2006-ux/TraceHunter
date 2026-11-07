"""TraceHunter TUI: trace list, step tree and details, all in the terminal."""

from typing import Any, List, Optional

from rich.console import Group
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree

from tracehunter.domain.models import Span, Trace
from tracehunter.domain.repository import TraceRepository
from tracehunter.tui.view import (
    COLUMNS,
    children_map,
    clip,
    matches,
    span_header,
    span_label,
    span_sections,
    summary,
    trace_row,
)

THEME = Theme(
    name="tracehunter",
    primary="#3fb950",
    secondary="#58a6ff",
    accent="#58a6ff",
    warning="#d29922",
    error="#f85149",
    success="#3fb950",
    foreground="#c9d1d9",
    background="#0d1117",
    surface="#161b22",
    panel="#161b22",
    dark=True,
)
_FIXED_WIDTHS = (2, 5, 14, 0, 5, 6, 8)  # a width of 0 = the "prompt" column takes whatever is left
_EMPTY_TREE = "select a trace"
_HINT = "[dim]↑↓ pick a step to see its input and output  ·  press ? for help[/]"


_HELP = """[b #3fb950]TraceHunter - how to move around[/]

[b]↑ ↓[/]  or  [b]j k[/]      move up and down
[b]Enter[/]            open the steps of the selected trace
[b]Tab[/] / [b]Shift+Tab[/]    switch panel  (Traces → Steps → Details)
[b]Esc[/]              back to the trace list / clear the search
[b]/[/]                search by prompt text         [b]f[/]  only failures
[b]e[/] / [b]c[/]            expand / collapse all steps
[b]r[/]                refresh now                   [b]q[/]  quit
[b]Mouse[/]            click rows and steps; scroll with the wheel
[b]Ctrl+P[/]           command palette (change the theme)

[dim]Press Esc, q or ? to close this help.[/]"""


class HelpScreen(ModalScreen[None]):
    """Help window with the key bindings; closes with Esc, q or ?."""

    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("q", "dismiss", show=False),
        Binding("question_mark", "dismiss", show=False),
    ]
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    #help-box { width: 70; height: auto; padding: 1 2; border: round #3fb950; background: #161b22; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(_HELP)

    def action_dismiss(self) -> None:  # type: ignore[override]
        self.dismiss(None)


class TraceHunterApp(App[None]):
    """Keyboard: ↑↓ or j/k, Enter opens, Tab switches panel, / searches, f failures, ? help."""

    TITLE = "TraceHunter"
    CSS = """
    Screen { background: #0d1117; }
    Header { background: #010409; color: #3fb950; }
    #stats { height: 1; padding: 0 2; background: #010409; color: #c9d1d9; }
    #search { height: 3; margin: 0 1; border: round #30363d; background: #0d1117; }
    #search:focus { border: round #58a6ff; }
    #body { height: 1fr; padding: 0 1; }
    #traces-box { width: 60%; border: round #30363d; border-title-color: #58a6ff; }
    #right { width: 40%; }
    #spans-box { height: 50%; border: round #30363d; border-title-color: #58a6ff; }
    #detail-box { height: 50%; border: round #30363d; border-title-color: #58a6ff; }
    #traces-box:focus-within, #spans-box:focus-within, #detail-box:focus-within {
        border: round #3fb950; border-title-color: #3fb950;
    }
    DataTable { height: 1fr; background: transparent; border: none; }
    DataTable > .datatable--cursor { background: #1f6feb 35%; }
    DataTable > .datatable--header { background: #161b22; color: #79c0ff; text-style: bold; }
    Tree { height: 1fr; background: transparent; border: none; padding: 0 1; }
    #detail { padding: 0 1; }
    Footer { background: #010409; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "focus_search", "Search"),
        Binding("f", "toggle_failed", "Failures"),
        Binding("e", "expand_all", "Expand"),
        Binding("c", "collapse_all", "Collapse"),
        Binding("question_mark", "help", "Help"),
        Binding("j", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False),
        Binding("escape", "clear_search", "Clear", show=False),
    ]

    def __init__(self, repository: TraceRepository, refresh_seconds: float = 2.0) -> None:
        super().__init__()
        self._repository = repository
        self._refresh_seconds = refresh_seconds
        self._traces: List[Trace] = []
        self._selected_id: Optional[str] = None
        self._failed_only = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="stats")
        yield Input(placeholder="/  filter by prompt text", id="search")
        with Horizontal(id="body"):
            with Vertical(id="traces-box"):
                yield DataTable(id="traces", cursor_type="row", zebra_stripes=True)
            with Vertical(id="right"):
                with Vertical(id="spans-box"):
                    yield Tree(_EMPTY_TREE, id="spans")
                with VerticalScroll(id="detail-box"):
                    yield Static(_HINT, id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = "tracehunter"
        self.query_one("#traces-box").border_title = "Traces"
        self.query_one("#spans-box").border_title = "Steps"
        self.query_one("#detail-box").border_title = "Details"
        self.query_one("#traces", DataTable).focus()
        self.action_refresh()
        self.set_interval(self._refresh_seconds, self.action_refresh)

    # ---- data ----
    def action_refresh(self) -> None:
        """Reload the traces from the repository, apply the filters and keep the selection."""
        self._traces = self._repository.list_traces(200)
        self._render_table()

    def _visible(self) -> List[Trace]:
        query = self.query_one("#search", Input).value.strip()
        return [t for t in self._traces if matches(t, query, self._failed_only)]

    def _prompt_width(self, table: DataTable[Any]) -> int:
        """Width left for the prompt column (the rest have a fixed width)."""
        fixed = sum(_FIXED_WIDTHS)
        return max(20, table.size.width - fixed - 2 * len(_FIXED_WIDTHS) - 2)

    def _render_table(self) -> None:
        visible = self._visible()
        table = self.query_one("#traces", DataTable)
        width = self._prompt_width(table)
        table.clear(columns=True)
        for label, fixed in zip(COLUMNS, _FIXED_WIDTHS, strict=True):
            table.add_column(label, width=fixed or width)
        for trace in visible:
            table.add_row(*trace_row(trace, width), key=trace.trace_id)
        ids = [t.trace_id for t in visible]
        if self._selected_id in ids:
            table.move_cursor(row=ids.index(str(self._selected_id)))
        elif ids:
            self._selected_id = ids[0]
        mode = "   [b yellow]· failures only[/]" if self._failed_only else ""
        self.query_one("#stats", Static).update(summary(visible) + mode)
        self._render_tree()

    def _render_tree(self) -> None:
        tree = self.query_one("#spans", Tree)
        trace = self._repository.get(self._selected_id) if self._selected_id else None
        tree.clear()
        if trace is None:
            tree.root.set_label(_EMPTY_TREE)
            return
        tree.root.set_label(f"[bold]{escape(clip(trace.name, 70))}[/]")
        groups = children_map(trace)

        def add(node: Any, parent: Optional[str]) -> None:
            for span in groups.get(parent, []):
                child = node.add(span_label(span), data=span, expand=True)
                add(child, span.span_id)

        add(tree.root, None)
        tree.root.expand()

    def _show_span(self, span: Span) -> None:
        parts: List[Any] = [Text.from_markup(span_header(span)), Text("")]
        for title, body in span_sections(span):
            parts.append(Text(title.upper(), style="bold cyan"))
            parts.append(
                Syntax(
                    body, "json", theme="github-dark", background_color="default", word_wrap=True
                )
            )
            parts.append(Text(""))
        self.query_one("#detail", Static).update(Group(*parts))

    # ---- events ----
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value and event.row_key.value != self._selected_id:
            self._selected_id = event.row_key.value
            self._render_tree()
            self.query_one("#detail", Static).update(_HINT)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.query_one("#spans", Tree).focus()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Any]) -> None:
        span = event.node.data
        if isinstance(span, Span):
            self._show_span(span)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._render_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#traces", DataTable).focus()

    # ---- actions ----
    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        self.query_one("#search", Input).value = ""
        self.query_one("#traces", DataTable).focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_move(self, delta: int) -> None:
        """j/k: move the cursor of the focused panel (like the arrow keys)."""
        widget = self.focused
        if isinstance(widget, (DataTable, Tree)):
            (widget.action_cursor_down if delta > 0 else widget.action_cursor_up)()

    def action_toggle_failed(self) -> None:
        self._failed_only = not self._failed_only
        self._render_table()

    def action_expand_all(self) -> None:
        self.query_one("#spans", Tree).root.expand_all()

    def action_collapse_all(self) -> None:
        tree = self.query_one("#spans", Tree)
        tree.root.collapse_all()
        tree.root.expand()


def run_tui(repository: TraceRepository, refresh_seconds: float = 2.0) -> None:
    """Open the TUI and return only when the user quits."""
    TraceHunterApp(repository, refresh_seconds).run()
