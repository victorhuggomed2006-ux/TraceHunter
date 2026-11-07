"""Estimated cost of a trace, from a bundled snapshot of public per-token list prices.

The snapshot (`prices.json`) comes from the OpenRouter model list and is refreshed by
`scripts/update_prices.py`. Nothing here touches the network. The result is only an estimate: it
uses list prices, so it does not reflect subscription plans, discounts or batch pricing.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

from tracehunter.domain.models import Span, Trace

_DEFAULT_FILE = Path(__file__).with_name("prices.json")
_DATE_SUFFIX = re.compile(r"-\d{8}$")
_VERSION_DASH = re.compile(r"(?<=\d)-(?=\d(?:\D|$))")


def normalize_model(name: str) -> str:
    """Turn a model name from a session file into the form used by the price table.

    `claude-sonnet-5-5` and `anthropic/claude-sonnet-5-5-20260101` both become
    `claude-sonnet-5.5`; a provider prefix is dropped.
    """
    text = name.strip().lower().split("/")[-1]
    text = text.split("[")[0]
    text = _DATE_SUFFIX.sub("", text)
    return _VERSION_DASH.sub(".", text)


@dataclass(frozen=True)
class ModelPrice:
    """USD per token for one model."""

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


class PriceTable:
    """Look up model prices and estimate what a span or a trace cost."""

    def __init__(self, prices: Mapping[str, ModelPrice], fetched: str = "") -> None:
        self._prices: Dict[str, ModelPrice] = {}
        for model_id, price in prices.items():
            self._prices[normalize_model(model_id)] = price
        self._fetched = fetched

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PriceTable":
        """Read a snapshot file (the bundled one by default); a bad file gives an empty table."""
        try:
            data = json.loads((path or _DEFAULT_FILE).read_text(encoding="utf-8"))
            prices = {
                model_id: ModelPrice(
                    float(raw.get("input", 0)),
                    float(raw.get("output", 0)),
                    float(raw.get("cache_read", 0)),
                    float(raw.get("cache_write", 0)),
                )
                for model_id, raw in data["models"].items()
            }
            return cls(prices, str(data.get("fetched", "")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls({})

    @property
    def fetched(self) -> str:
        """Date of the price snapshot (YYYY-MM-DD), or an empty string."""
        return self._fetched

    def lookup(self, model: object) -> Optional[ModelPrice]:
        """Price of a model, or None when the model is unknown."""
        if not isinstance(model, str) or not model:
            return None
        return self._prices.get(normalize_model(model))

    def span_cost(self, span: Span) -> Optional[float]:
        """Estimated USD cost of one span, or None when it has no tokens or an unknown model."""
        price = self.lookup(span.metadata.get("model"))
        if price is None:
            return None
        counts = {key: _count(span.metadata.get(key)) for key in _TOKEN_KEYS}
        if not any(counts.values()):
            return None
        return (
            counts["input_tokens"] * price.input
            + counts["output_tokens"] * price.output
            + counts["cache_read_tokens"] * price.cache_read
            + counts["cache_creation_tokens"] * price.cache_write
        )

    def trace_cost(self, trace: Trace) -> Optional[float]:
        """Estimated USD cost of a trace: the sum over the spans it can price, else None."""
        costs = [c for c in (self.span_cost(s) for s in trace.spans) if c is not None]
        return sum(costs) if costs else None


_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
