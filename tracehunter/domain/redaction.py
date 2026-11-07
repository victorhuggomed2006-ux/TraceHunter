"""Mask common secrets and limit text length before storing it."""

import re
from typing import Any, List

_SECRET_PATTERNS: List["re.Pattern[str]"] = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"[rsp]k_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"npm_[A-Za-z0-9]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"ya29\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
]
# user:password@host inside URLs
_URL_CREDENTIALS = re.compile(r"(?<=://)([^/\s:@]+):([^/\s@]+)@")
# KEY=value, key: value and "key": "value" where the key NAME contains a secret-like word
# (DB_PASSWORD, AWS_SECRET_ACCESS_KEY, client_secret...). The affixes are bounded so a long run of
# word characters cannot make the regex slow.
_ASSIGNMENT = re.compile(
    r"(?i)([\w.\-]{0,40}(?:password|passwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|credentials?)[\w.\-]{0,40})"
    r"""(["']?\s*[=:]\s*["']?)([^\s"',;&]+)"""
)
MASK = "***"


def redact(text: str) -> str:
    """Mask common secret formats, URL credentials and values of secret-looking keys (best effort).

    Not a guarantee: a secret in an unusual format or inside free text can still get through.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    text = _URL_CREDENTIALS.sub(lambda m: f"{m.group(1)}:{MASK}@", text)
    return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)


def clip(text: str, limit: int) -> str:
    """Cut the text to `limit` characters, marking the cut with an ellipsis."""
    return text if len(text) <= limit else text[:limit] + "…"


def safe_text(value: Any, limit: int = 400) -> str:
    """Convert to text, mask secrets and limit the length. Never raises."""
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break recording
        text = f"<{type(value).__name__}>"
    # Cut first: a huge output (e.g. a whole file) never needs to go through the regexes in full.
    return clip(redact(text[: limit * 4]), limit)
