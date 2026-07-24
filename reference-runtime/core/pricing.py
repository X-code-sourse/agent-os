"""
Intent OS — Model Pricing Data (Externalized)

All model pricing lives here so it can be updated without code changes.
Prices are loaded from ~/.intent-os/pricing.yaml if it exists, falling back
to the DEFAULT_PRICING table below.

YAML file prices override defaults — add your own models or adjust rates
without touching source code.
"""

from __future__ import annotations

from pathlib import Path

PRICING_FILE = Path.home() / ".intent-os" / "pricing.yaml"

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "o3": {"input": 10.00, "output": 40.00},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    # Claude Opus 4.8 (1M context)
    "claude-opus-4-8": {"input": 15.00, "output": 75.00},
    # Gemma
    "gemma-3-27b-it": {"input": 0.15, "output": 0.60},
    # Gemini
    "gemini-2.5-pro": {"input": 3.50, "output": 14.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 1.20},
    # DeepSeek
    "deepseek-v3": {"input": 0.27, "output": 1.10},
    "deepseek-r1": {"input": 0.55, "output": 2.19},
    # Mistral
    "mistral-large": {"input": 2.00, "output": 6.00},
    "mistral-small": {"input": 0.20, "output": 0.60},
    # Llama
    "llama-4-maverick": {"input": 0.20, "output": 0.90},
    "llama-4-scout": {"input": 0.10, "output": 0.40},
}

# Models with zero cost (local / free tier)
ZERO_COST_MODELS: set[str] = set()

# Default model per adapter
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4",
    "ollama": "llama3.2:1b",
    "openrouter": "gpt-4o",
    "github-models": "gpt-4o-mini",
}

# Model context windows (tokens) — used to detect near-limit usage
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o":                 128_000,
    "gpt-4o-mini":            128_000,
    "gpt-4.1":                1_000_000,
    "gpt-4.1-mini":           1_000_000,
    "gpt-4.1-nano":           1_000_000,
    "o3":                     200_000,
    "o4-mini":                200_000,
    "o1":                     200_000,
    "o1-mini":                200_000,
    "claude-sonnet-4":        200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-3.5-sonnet":      200_000,
    "claude-opus-4":          200_000,
    "claude-haiku-3.5":       200_000,
    "claude-opus-4-8":        1_000_000,
    "gemma-3-27b-it":         128_000,
    "gemini-2.5-pro":         1_000_000,
    "gemini-2.5-flash":       1_000_000,
    "deepseek-v3":            128_000,
    "deepseek-r1":            128_000,
    "mistral-large":          128_000,
    "mistral-small":          128_000,
    "llama-4-maverick":       1_000_000,
    "llama-4-scout":          10_000_000,
}

# Cheaper alternative for each model (sorted by cost, same provider preferred)
CHEAPER_ALTERNATIVES: dict[str, list[tuple[str, str]]] = {
    "claude-opus-4": [
        ("claude-sonnet-4", "Same provider — Sonnet 4 is 5x cheaper input, 5x cheaper output"),
        ("claude-haiku-3.5", "Same provider — Haiku is 18x cheaper input, 18x cheaper output"),
        ("gpt-4o-mini", "Cross-provider — GPT-4o mini is 100x cheaper input than Opus"),
    ],
    "claude-sonnet-4": [
        ("claude-haiku-3.5", "Same provider — Haiku is 3.75x cheaper input, 3.75x cheaper output"),
    ],
    "claude-3.5-sonnet": [
        ("claude-haiku-3.5", "Same provider — Haiku is 3.75x cheaper input, 3.75x cheaper output"),
    ],
    "gpt-4o": [
        ("gpt-4.1", "Same provider — GPT-4.1 is 20% cheaper input, same family"),
        ("gpt-4o-mini", "Same provider — GPT-4o mini is 16x cheaper"),
    ],
    "o3": [
        ("o4-mini", "Same provider — o4-mini is 9x cheaper input, 9x cheaper output"),
    ],
    "o1": [
        ("o1-mini", "Same provider — o1-mini is 13x cheaper input, 13x cheaper output"),
        ("o4-mini", "Same provider — o4-mini is 13x cheaper input, 13x cheaper output"),
    ],
}


def load_pricing() -> dict[str, dict[str, float]]:
    """Load pricing from YAML file, falling back to defaults.

    If ``~/.intent-os/pricing.yaml`` exists, its entries are merged on top of
    DEFAULT_PRICING — file prices override defaults.  Unknown keys in the file
    are added as new model entries.

    Returns the merged dictionary.
    """
    pricing = dict(DEFAULT_PRICING)  # shallow copy

    if PRICING_FILE.exists():
        try:
            import yaml
        except ImportError:
            # If PyYAML isn't available, try the YAML parser bundled with
            # the standard library (Python 3.13+) or fall back gracefully.
            try:
                import yaml  # type: ignore[no-redef]
            except ImportError:
                return pricing

        try:
            with open(PRICING_FILE, "r", encoding="utf-8") as fh:
                file_data = yaml.safe_load(fh)
            if isinstance(file_data, dict):
                for model, rates in file_data.items():
                    if isinstance(rates, dict):
                        entry: dict[str, float] = {}
                        if "input" in rates:
                            entry["input"] = float(rates["input"])
                        if "output" in rates:
                            entry["output"] = float(rates["output"])
                        if entry:
                            pricing[str(model)] = entry
        except Exception:
            # Corrupt or unparseable file — silently fall back to defaults.
            pass

    return pricing


def save_pricing(pricing: dict[str, dict[str, float]]) -> None:
    """Write *pricing* to ``~/.intent-os/pricing.yaml`` as YAML."""
    PRICING_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        import yaml
    except ImportError:
        # Write as JSON if PyYAML is not available
        import json
        with open(PRICING_FILE, "w", encoding="utf-8") as fh:
            json.dump(pricing, fh, indent=2)
        return

    with open(PRICING_FILE, "w", encoding="utf-8") as fh:
        yaml.safe_dump(pricing, fh, default_flow_style=False, sort_keys=False)


def get_price(model: str) -> dict[str, float]:
    """Return ``{"input": X, "output": Y}`` for a model.

    Uses **substring matching** so that a versioned model string like
    ``"claude-sonnet-4-20250514"`` matches the base entry
    ``"claude-sonnet-4"``.

    Falls back to the DEFAULT_PRICING default (2.50 / 10.00) for unknown models.
    """
    pricing = load_pricing()

    # Exact match first
    if model in pricing:
        return dict(pricing[model])

    # Build a canonical key: lowercase, strip whitespace
    model_key = model.strip().lower()

    # Sort by key length descending so longer (more specific) names match first
    for known in sorted(pricing, key=len, reverse=True):
        if known.lower() in model_key:
            return dict(pricing[known])

    # Fallback
    return {"input": 2.50, "output": 10.00}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a model call.

    Uses :func:`load_pricing` for the current pricing table (including any
    user overrides from ``~/.intent-os/pricing.yaml``).
    """
    price = get_price(model)
    return (
        input_tokens / 1_000_000 * price["input"]
        + output_tokens / 1_000_000 * price["output"]
    )


def model_display_name(model: str) -> str:
    """Human-readable model name with pricing.

    e.g. ``'claude-opus-4 ($15/$75 per 1M tokens)'``.
    """
    p = get_price(model)
    return f"{model} (${p['input']:.0f}/${p['output']:.0f} per 1M tokens)"
