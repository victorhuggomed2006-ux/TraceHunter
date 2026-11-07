"""Usage: tracehunter [db] [--claude-code] (web UI) or tracehunter tui [db] (terminal)."""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from tracehunter import __version__
from tracehunter.domain.repository import TraceRepository

_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _parse_args(argv: Optional[Sequence[str]], prog: str = "tracehunter") -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Opens the local read-only web interface for traces (no login). "
        "Use `tracehunter tui` for the terminal version.",
        epilog="Environment: TRACEHUNTER_HOST, TRACEHUNTER_PORT, TRACEHUNTER_ALLOWED_HOSTS.",
    )
    parser.add_argument(
        "database",
        nargs="?",
        default="tracehunter.db",
        help="SQLite file (default: tracehunter.db)",
    )
    parser.add_argument(
        "--claude-code",
        action="store_true",
        help="show this computer's Claude Code sessions live (read-only)",
    )
    parser.add_argument(
        "--claude-dir", type=Path, help="sessions folder (default: ~/.claude/projects)"
    )
    parser.add_argument(
        "--max-sessions", type=int, default=8, help="recent sessions read (default: 8)"
    )
    parser.add_argument("--sync-interval", type=float, default=2.0, help="seconds between reads")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _allowed_hosts(default: Sequence[str]) -> List[str]:
    """Read TRACEHUNTER_ALLOWED_HOSTS (comma-separated list); fall back to the default."""
    raw = os.environ.get("TRACEHUNTER_ALLOWED_HOSTS", "")
    return [h.strip() for h in raw.split(",") if h.strip()] or list(default)


def _start_claude_code_sync(args: argparse.Namespace, repository: TraceRepository) -> None:
    from tracehunter.application.collector_sync import CollectorSync
    from tracehunter.infrastructure.claude_code_collector import ClaudeCodeCollector

    collector = ClaudeCodeCollector(args.claude_dir, args.max_sessions)
    sync = CollectorSync(collector, repository, args.sync_interval)
    try:
        first = f"{sync.sync_once()} traces read"
    except Exception as error:  # noqa: BLE001 - the background loop will retry
        first = f"first read failed ({type(error).__name__}), will retry"
    sys.stderr.write(f"Claude Code: {first}; refreshing every {args.sync_interval}s\n")
    sync.start()


def _main_tui(tokens: Sequence[str]) -> None:
    """`tracehunter tui`: open the terminal interface instead of the web server."""
    args = _parse_args(tokens, prog="tracehunter tui")
    try:
        from tracehunter.tui.app import run_tui
    except ImportError:
        sys.stderr.write('The terminal UI needs textual: pip install "tracehunter[tui]"\n')
        raise SystemExit(1) from None
    from tracehunter.infrastructure.sqlite_repository import SQLiteTraceRepository

    repository = SQLiteTraceRepository(args.database)
    if args.claude_code:
        _start_claude_code_sync(args, repository)
    run_tui(repository, args.sync_interval)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Start the web server (by default only on 127.0.0.1:8000) or, with `tui`, the terminal UI."""
    tokens = list(sys.argv[1:] if argv is None else argv)
    if tokens[:1] == ["tui"]:
        _main_tui(tokens[1:])
        return
    args = _parse_args(tokens)
    try:
        import uvicorn

        from tracehunter.api.app import DEFAULT_ALLOWED_HOSTS, create_app
    except ImportError:
        sys.stderr.write(
            'The web interface needs fastapi and uvicorn: pip install "tracehunter[server]"\n'
        )
        raise SystemExit(1) from None
    from tracehunter.infrastructure.sqlite_repository import SQLiteTraceRepository

    host = os.environ.get("TRACEHUNTER_HOST", "127.0.0.1")
    port = int(os.environ.get("TRACEHUNTER_PORT", "8000"))
    if host not in _LOOPBACK:
        sys.stderr.write(
            f"WARNING: listening on {host}, and the interface has no login. "
            "Anyone on the network can read the traces (they may hold prompts and secrets).\n"
        )
    repository = SQLiteTraceRepository(args.database)
    if args.claude_code:
        _start_claude_code_sync(args, repository)
    app = create_app(repository, _allowed_hosts(DEFAULT_ALLOWED_HOSTS))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
