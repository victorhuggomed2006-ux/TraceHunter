"""Refresh `tracehunter/domain/prices.json` from the public OpenRouter model list.

Run by the maintainer when prices change (`python scripts/update_prices.py`). TraceHunter itself
never calls the network: it only reads the bundled snapshot this script writes.
"""

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict

URL = "https://openrouter.ai/api/v1/models"
OUTPUT = Path(__file__).resolve().parent.parent / "tracehunter" / "domain" / "prices.json"
PROVIDERS = ("anthropic", "openai", "google", "deepseek", "x-ai", "qwen", "moonshotai")
FIELDS = {
    "input": "prompt",
    "output": "completion",
    "cache_read": "input_cache_read",
    "cache_write": "input_cache_write",
}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build(models: Any) -> Dict[str, Any]:
    """Keep the main providers' base models (no ':free' or ':batch' variants), USD per token."""
    prices: Dict[str, Dict[str, float]] = {}
    for model in models:
        model_id = str(model.get("id", ""))
        if ":" in model_id or model_id.split("/")[0] not in PROVIDERS:
            continue
        raw = model.get("pricing") or {}
        entry = {name: _number(raw.get(key)) for name, key in FIELDS.items()}
        if entry["input"] or entry["output"]:
            prices[model_id] = entry
    return {
        "source": "https://openrouter.ai/api/v1/models",
        "fetched": date.today().isoformat(),
        "unit": "USD per token",
        "models": dict(sorted(prices.items())),
    }


def main() -> int:
    with urllib.request.urlopen(URL, timeout=60) as response:  # noqa: S310 - fixed https URL
        data = json.load(response)["data"]
    snapshot = build(data)
    OUTPUT.write_text(json.dumps(snapshot, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(f"{len(snapshot['models'])} models written to {OUTPUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
