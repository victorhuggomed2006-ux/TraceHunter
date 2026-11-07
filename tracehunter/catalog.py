"""Catalog of known AI CLIs and where each one stores its sessions.

Compiled from web research on 2026-11-06. Each entry states how reliable the
path is; only `VERIFIED_LOCAL` entries were seen on disk.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Tuple


class Confidence(str, Enum):
    """How far the sessions path of a tool can be trusted."""

    VERIFIED_LOCAL = "verified by the maintainer"
    OFFICIAL = "official documentation"
    THIRD_PARTY = "third-party sources only"
    UNKNOWN = "path unknown"


@dataclass(frozen=True)
class CliTool:
    """An AI CLI and the folder where it stores its session history."""

    name: str
    vendor: str
    sessions_path: Optional[str]
    confidence: Confidence
    note: str = ""

    @property
    def has_path(self) -> bool:
        return self.sessions_path is not None


class Catalog:
    """Searchable collection of `CliTool`."""

    def __init__(self, tools: Iterable[CliTool]) -> None:
        self._tools: Tuple[CliTool, ...] = tuple(tools)

    def __len__(self) -> int:
        return len(self._tools)

    @property
    def tools(self) -> List[CliTool]:
        return list(self._tools)

    def find(self, name: str) -> Optional[CliTool]:
        """Look up by name, case-insensitive."""
        wanted = name.lower()
        return next((t for t in self._tools if t.name.lower() == wanted), None)

    def by_confidence(self, *levels: Confidence) -> List[CliTool]:
        """Tools whose confidence level is among `levels`."""
        return [t for t in self._tools if t.confidence in levels]


_C = Confidence

DEFAULT_CATALOG = Catalog(
    [
        # Large companies
        CliTool("Claude Code", "Anthropic", "~/.claude/projects/*/*.jsonl", _C.VERIFIED_LOCAL),
        CliTool(
            "Codex CLI",
            "OpenAI",
            "~/.codex/sessions/",
            _C.THIRD_PARTY,
            "Sessions folder not yet confirmed on disk",
        ),
        CliTool(
            "Gemini CLI",
            "Google",
            "~/.gemini/tmp/<project>/chats/",
            _C.THIRD_PARTY,
            "Reportedly replaced by Antigravity CLI",
        ),
        CliTool(
            "Antigravity CLI",
            "Google",
            None,
            _C.UNKNOWN,
            "Successor to Gemini CLI; sessions folder not yet documented",
        ),
        CliTool(
            "Copilot CLI",
            "GitHub",
            "~/.copilot/session-state/",
            _C.OFFICIAL,
            "COPILOT_HOME changes the root",
        ),
        CliTool(
            "Kiro CLI",
            "Amazon",
            "~/.kiro/",
            _C.OFFICIAL,
            "SQLite database; formerly Q Developer CLI",
        ),
        CliTool(
            "Mistral Vibe", "Mistral", "~/.vibe/logs/", _C.OFFICIAL, "VIBE_HOME changes the root"
        ),
        CliTool(
            "Cursor CLI", "Cursor", "~/.cursor/projects/<slug>/agent-transcripts/", _C.THIRD_PARTY
        ),
        CliTool("Grok Build", "xAI", None, _C.UNKNOWN, "Reported as beta since May 2026"),
        CliTool("Junie CLI", "JetBrains", None, _C.UNKNOWN),
        CliTool("Devin CLI", "Cognition", None, _C.UNKNOWN),
        CliTool("Bob Shell", "IBM", None, _C.UNKNOWN),
        CliTool("Warp", "Warp", None, _C.UNKNOWN),
        CliTool("Tabnine CLI", "Tabnine", None, _C.UNKNOWN),
        # Chinese ecosystem
        CliTool(
            "Kimi Code",
            "Moonshot",
            "~/.kimi-code/sessions/<workspaceId>/<sessionId>/",
            _C.OFFICIAL,
            "KIMI_CODE_HOME changes the root; old layout in ~/.kimi/",
        ),
        CliTool("Qwen Code", "Alibaba", "~/.qwen/projects/<cwd>/chats/<id>.jsonl", _C.THIRD_PARTY),
        CliTool("MiniMax CLI", "MiniMax", None, _C.UNKNOWN),
        CliTool("Trae CLI", "ByteDance", None, _C.UNKNOWN),
        CliTool("ComateCLI", "Baidu", None, _C.UNKNOWN),
        CliTool("CodeBuddy Code", "Tencent", None, _C.UNKNOWN),
        CliTool("MiMo Code", "Xiaomi", None, _C.UNKNOWN, "Based on a fork of OpenCode"),
        # Open source and independent
        CliTool("Aider", "Aider-AI", ".aider.chat.history.md (in the project folder)", _C.OFFICIAL),
        CliTool(
            "OpenCode",
            "OpenCode",
            "~/.local/share/opencode/opencode.db",
            _C.OFFICIAL,
            "SQLite; OPENCODE_DB changes the file",
        ),
        CliTool(
            "Goose",
            "Block",
            "~/.local/share/goose/sessions/sessions.db",
            _C.OFFICIAL,
            "Documented for Linux only",
        ),
        CliTool(
            "Cline CLI", "Cline", "~/.cline/data/", _C.OFFICIAL, "sessions/ subfolder not confirmed"
        ),
        CliTool(
            "Crush", "Charm", None, _C.UNKNOWN, "State only in ~/.local/share/crush/crush.json"
        ),
        CliTool("Kilo", "Kilo-Org", None, _C.UNKNOWN),
        CliTool("Continue CLI", "Continue", None, _C.UNKNOWN),
        CliTool("Roo Code", "RooCode", None, _C.UNKNOWN),
        CliTool(
            "Plandex", "Plandex", None, _C.UNKNOWN, "Cloud version reportedly shut down in Oct 2025"
        ),
        CliTool("OpenHands", "All Hands", None, _C.UNKNOWN),
        CliTool("gptme", "gptme", None, _C.UNKNOWN),
        CliTool("Amp", "Sourcegraph", None, _C.UNKNOWN),
        CliTool("Droid", "Factory", None, _C.UNKNOWN),
        CliTool("Pi", "badlogic", None, _C.UNKNOWN),
        CliTool("Forge", "antinomyhq", None, _C.UNKNOWN),
        CliTool("Codebuff", "Codebuff", None, _C.UNKNOWN),
        CliTool(
            "OpenClaw",
            "OpenClaw",
            "~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite",
            _C.OFFICIAL,
            "OPENCLAW_STATE_DIR changes the root; old layout in agents/<id>/sessions/sessions.json",
        ),
        CliTool(
            "OpenClaude",
            "Gitlawb",
            "~/.openclaude/bg-sessions/",
            _C.THIRD_PARTY,
            "Claude Code-compatible CLI; does not read ~/.claude; "
            "sources disagree on the config variable",
        ),
        CliTool(
            "open-claude-code",
            "ruvnet",
            None,
            _C.UNKNOWN,
            "Independent reimplementation, unverified",
        ),
        # General purpose
        CliTool("Ollama", "Ollama", None, _C.UNKNOWN, "Stores models, not conversations"),
        CliTool("llm", "Simon Willison", "`llm logs path` (logs.db)", _C.OFFICIAL),
        CliTool("shell_gpt", "TheR1D", "CHAT_CACHE_PATH", _C.OFFICIAL, "Default not confirmed"),
        CliTool("fabric", "Daniel Miessler", None, _C.UNKNOWN),
        CliTool("aichat", "sigoden", "`aichat --info` (sessions_dir)", _C.OFFICIAL),
        CliTool("mods", "Charm", None, _C.UNKNOWN, "Reportedly archived in Mar 2026"),
        CliTool("LM Studio CLI", "LM Studio", None, _C.UNKNOWN),
        CliTool(
            "Jan",
            "Jan",
            "%APPDATA%/Jan/data/threads/<id>/messages.jsonl",
            _C.OFFICIAL,
            "Desktop app, not a CLI",
        ),
        CliTool("Open Interpreter", "OpenInterpreter", "~/.openinterpreter", _C.THIRD_PARTY),
    ]
)
