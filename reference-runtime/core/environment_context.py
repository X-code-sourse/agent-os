"""
Intent OS — Environment Context (SPEC-0010 Layer 6)

Auto-detects the runtime environment: available adapters, platform info,
model pricing coverage.

Pure computation — no state, no database. Called at runtime to tell the
agent "where you are and what you can use."

Usage::

    from core.environment_context import detect_environment

    env = detect_environment()
    print(env.available_adapters)  # ["openai", "ollama"]
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EnvironmentProfile:
    """What this runtime instance offers the agent."""
    runtime_version: str = ""
    platform: str = ""
    python_version: str = ""
    available_adapters: list[str] = field(default_factory=list)
    default_adapter: str = ""
    tools: list[str] = field(default_factory=list)
    has_model_pricing_override: bool = False


def _check_ollama() -> bool:
    """Quick availability check — ping Ollama API."""
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=1)
        return resp.status == 200
    except Exception:
        return False


def detect_environment() -> EnvironmentProfile:
    """Auto-detect the runtime environment.

    Checks:
    - Environment variables for API keys (openai, anthropic, openrouter)
    - Whether Ollama is running locally
    - Whether a custom pricing.yaml exists
    - Python version and platform
    """
    adapters: list[str] = []

    # Check cloud adapters by env var
    if os.environ.get("OPENAI_API_KEY"):
        adapters.append("openai")
    if os.environ.get("ANTHROPIC_API_KEY"):
        adapters.append("anthropic")
    if os.environ.get("OPENROUTER_API_KEY"):
        adapters.append("openrouter")
    if os.environ.get("GITHUB_TOKEN"):
        adapters.append("github-models")

    # Check Ollama (local, no env var needed)
    if _check_ollama():
        adapters.append("ollama")

    # Determine default adapter
    default = "ollama" if "ollama" in adapters else (adapters[0] if adapters else "")

    # Check pricing override
    pricing_path = Path.home() / ".intent-os" / "pricing.yaml"
    has_pricing = pricing_path.exists()

    # Tools available to this runtime
    tools = ["filesystem_read", "filesystem_write", "env_read", "network_access"]

    return EnvironmentProfile(
        runtime_version="intent-os 0.12.0",
        platform=sys.platform,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        available_adapters=adapters,
        default_adapter=default,
        tools=tools,
        has_model_pricing_override=has_pricing,
    )


def format_environment(env: EnvironmentProfile | None = None) -> str:
    """Format environment context for prompt injection."""
    if env is None:
        env = detect_environment()

    lines: list[str] = []
    lines.append(f"Runtime: {env.runtime_version} on {env.platform}")
    if env.available_adapters:
        lines.append(f"Available adapters: {', '.join(sorted(env.available_adapters))}")
    if env.default_adapter:
        lines.append(f"Default: {env.default_adapter}")
    return "\n".join(lines)
