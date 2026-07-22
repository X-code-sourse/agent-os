"""
Intent OS — CLI Shared Helpers

Shared utility functions used by all CLI command modules.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from core.executor import Executor
from core.models import ValidationError
from core.parser import parse_manifest, ManifestParseError


_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def load_manifest(path_str: str) -> tuple[Any, Any]:
    """Load and validate a manifest file."""
    path = Path(path_str)
    if not path.exists():
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    if path.suffix not in (".yaml", ".yml"):
        print(f"Warning: Expected .yaml file, got '{path.suffix}'", file=sys.stderr)

    try:
        manifest, validation = parse_manifest(path)
    except ManifestParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if validation.errors:
        print("Manifest validation errors:", file=sys.stderr)
        for err in validation.errors:
            print(f"  [{err.severity}] {err.field}: {err.message}", file=sys.stderr)
        sys.exit(1)

    if validation.warnings:
        for warn in validation.warnings:
            print(f"  [{warn.severity}] {warn.field}: {warn.message}", file=sys.stderr)

    print(f"[OK] Manifest '{manifest.id}' loaded successfully")
    return manifest, validation


# -- Built-in manifest resolution ------------------------------------------

BUILTIN_MANIFEST_DIRS: list[Path] = [
    Path(__file__).parent.parent / "examples",      # reference-runtime/examples/
    Path(__file__).parent.parent.parent / "examples",  # project-root/examples/
]


def find_builtin_manifest(name: str) -> Path | None:
    """Resolve a capability *name* (without ``.yaml`` extension) to a
    built-in manifest file path on disk.

    Searches ``BUILTIN_MANIFEST_DIRS`` in order.  Returns ``None``
    when no file matches.
    """
    for base in BUILTIN_MANIFEST_DIRS:
        for suffix in (".yaml", ".yml"):
            candidate = base / f"{name}{suffix}"
            if candidate.exists():
                return candidate
    return None


def list_builtin_capabilities() -> list[dict[str, str]]:
    """Return a list of ``{name, description}`` dicts for every built-in
    manifest found on disk.  Deduplicates by name (first directory wins)."""
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for base_dir in BUILTIN_MANIFEST_DIRS:
        if not base_dir.is_dir():
            continue
        for yaml_file in sorted(base_dir.glob("*.yaml")):
            name = yaml_file.stem
            if name in seen:
                continue
            seen.add(name)
            import yaml
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                meta = data.get("metadata", {})
                results.append({
                    "name": meta.get("name", name),
                    "description": meta.get("description", ""),
                })
            except Exception:
                results.append({"name": name, "description": ""})
    return results


def _adapter_has_credentials(name: str) -> bool:
    """Return ``True`` when the API-keys / local server needed by *name* appear to be present.

    This prevents cloud-only adapters from being registered when the user
    hasn't set the corresponding environment variable, which would otherwise
    cause silent failures or force the user to always pass ``--adapter ollama``.
    """
    checks = {
        "openai":         "OPENAI_API_KEY",
        "anthropic":      "ANTHROPIC_API_KEY",
        "openrouter":     "OPENROUTER_API_KEY",
        "github-models":  "GITHUB_TOKEN",
    }
    env_var = checks.get(name)
    if env_var is None:
        return True       # local adapters (ollama, simulated) — no key needed
    return bool(os.environ.get(env_var))


def setup_executor(adapters: list[str] | None = None) -> Executor:
    """Create an executor with the requested adapters loaded."""
    executor = Executor()
    has_api_keys = bool(os.environ.get("OPENAI_API_KEY")) or bool(os.environ.get("OPENROUTER_API_KEY"))
    has_ollama = False
    adapter_classes = []

    # Optional adapter packages — gracefully degrade if not installed
    for adapter_module, adapter_cls, adapter_name in [
        ("adapters.openai_adapter", "OpenAIAdapter", "openai"),
        ("adapters.anthropic_adapter", "AnthropicAdapter", "anthropic"),
        ("adapters.github_models_adapter", "GitHubModelsAdapter", "github-models"),
        ("adapters.openrouter_adapter", "OpenRouterAdapter", "openrouter"),
        ("adapters.ollama_adapter", "OllamaAdapter", "ollama"),
    ]:
        try:
            mod = __import__(adapter_module, fromlist=[adapter_cls])
            cls = getattr(mod, adapter_cls)
            adapter_classes.append((adapter_name, cls))
        except ImportError:
            pass  # Optional dependency not installed — skip

    for name, adapter_cls in adapter_classes:
        # Skip cloud adapters whose credentials aren't set
        if not _adapter_has_credentials(name):
            continue
        try:
            adapter = adapter_cls()
            if adapter.name == "ollama":
                try:
                    import urllib.request
                    req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
                    resp = urllib.request.urlopen(req, timeout=1)
                    if resp.status == 200:
                        executor.register_adapter(adapter.name, adapter)
                        has_ollama = True
                except Exception:
                    pass  # Ollama not running — skip local adapter
            else:
                executor.register_adapter(adapter.name, adapter)
        except Exception as exc:
            print(f"  Warning: Failed to load {adapter_cls.__name__}: {exc}", file=sys.stderr)

    if executor.get_available_adapters():
        print(f"  Adapters loaded: {', '.join(executor.get_available_adapters())}")
        if has_ollama and not has_api_keys:
            print(f"  Using local Ollama (free, no API key needed)")
            print(f"  Tip: Set OPENAI_API_KEY or OPENROUTER_API_KEY for cloud models")
    else:
        print("  Warning: No runtime adapters available.")
        print()
        print("  Install Ollama (free, local, no API key):")
        print("    https://ollama.com/download")
        print("    ollama pull llama3.2:1b")
        print("    ollama serve")
        print()
        print("  Or set an API key:")
        print("    export OPENAI_API_KEY=sk-...")
        print()
    return executor


def get_registry_store() -> tuple[Path, Any]:
    """Get or create the default persistent registry store."""
    store_dir = Path.home() / ".intent-os"
    store_dir.mkdir(parents=True, exist_ok=True)
    db_path = store_dir / "store.db"
    from core.registry import CapabilityRegistry
    registry = CapabilityRegistry(db_path=str(db_path))
    return db_path, registry


def get_event_store() -> Any:
    """Get or create the default persistent Event Store."""
    store_dir = Path.home() / ".intent-os"
    store_dir.mkdir(parents=True, exist_ok=True)
    db_path = store_dir / "events.db"
    from core.event_store import EventStore
    return EventStore(db_path=str(db_path))


def save_to_event_store(record: Any) -> None:
    """Save an ExecutionRecord to the default Event Store."""
    store = get_event_store()
    store.save_events_batch(record.events)
    store.save_execution_record(record)


def display_record(record: Any, output_file: str | None = None) -> None:
    """Display execution record results."""
    print(f"\n{'='*60}")
    print(f"EXECUTION RESULT")
    print(f"{'='*60}")
    print(f"  Status: {record.status.value}")
    if record.error:
        print(f"  Error: {record.error}")
    print(f"  Runtime: {record.runtime_id} via {record.adapter}")
    print(f"  Latency: {record.total_latency_ms:.0f}ms")
    print(f"  Cost: ${record.total_cost_usd:.4f}")
    print(f"  Tokens: {record.total_tokens}")
    print(f"  Events: {len(record.events)}")
    if record.output:
        print(f"\n  Output:")
        output_str = json.dumps(
            {k: v for k, v in record.output.items() if not k.startswith("_")},
            indent=4, default=str,
        )
        for line in output_str.split("\n"):
            print(f"    {line}")
    if record.events:
        print(f"\n  Event Sequence:")
        for evt in record.events:
            marker = {
                "TaskStarted": ">>", "CapabilityInvoked": "->",
                "TaskCompleted": "OK", "TaskFailed": "!!",
            }.get(evt.event_type.value, "..")
            extra = ""
            if evt.metrics and "latency_ms" in evt.metrics:
                extra = f" ({evt.metrics['latency_ms']}ms)"
            print(f"    {marker} {evt.event_type.value}{extra}")
    if output_file:
        with open(output_file, "w") as f:
            f.write(json.dumps(record.to_dict(), indent=2, default=str))
        print(f"\n  Full record written to: {output_file}")


def print_table(headers: list[str], rows: list[tuple[str, list[str]]]) -> None:
    """Print a simple ASCII table."""
    col_width = max(len(h) for h in headers)
    for label, values in rows:
        col_width = max(col_width, len(label))
        for v in values:
            col_width = max(col_width, len(v))
    col_width = max(col_width + 2, 12)
    header_line = "  " + "".join(h.ljust(col_width) for h in headers)
    print(header_line)
    print("  " + "-" * len(header_line))
    for label, values in rows:
        print(f"  {label.ljust(col_width)}" + "".join(v.ljust(col_width) for v in values))
