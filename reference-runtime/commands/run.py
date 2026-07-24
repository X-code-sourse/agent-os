"""Intent OS CLI — run command."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from core.recorder import save_execution_record
from commands.helpers import load_manifest, find_builtin_manifest
from commands.helpers import setup_executor, save_to_event_store, display_record
from commands.helpers import list_builtin_capabilities

# Lazy-imported helpers used only on specific code paths


def _looks_like_file_path(name: str) -> bool:
    """Return ``True`` when *name* looks like a file path (has a YAML
    extension, or contains a path separator), meaning it should be
    resolved as a file rather than as a built-in capability name."""
    return name.endswith((".yaml", ".yml")) or "/" in name or "\\" in name


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a capability.

    The first positional argument can be either a **file path** to a
    ``.yaml`` manifest **or** a bare capability name (e.g. ``translate``)
    that is resolved from the project's built-in examples.

    Input data can be supplied as:
    - ``--input`` / ``-i``: a JSON string (existing behaviour).
    - ``--input-file`` / ``-f``: a JSON file path (existing behaviour).
    - ``--param`` / ``-p``: one or more ``key=value`` pairs.
    - Positional ``text`` (only when the manifest has a ``text`` field): the
      remaining words after the capability name.
    """
    # ---- 1. Resolve manifest -------------------------------------------
    manifest_ref = args.manifest

    if _looks_like_file_path(manifest_ref):
        # File path — standard loading (load_manifest handles missing files)
        manifest, _ = load_manifest(manifest_ref)
    else:
        # Bare name — try built-in resolution first
        resolved = find_builtin_manifest(manifest_ref)
        if resolved is not None:
            manifest, _ = load_manifest(str(resolved))
            print(f"  (resolved from built-in: {resolved})")
        else:
            # Show available built-in capabilities
            builtins = list_builtin_capabilities()
            lines = [
                f"Error: '{manifest_ref}' is not a file and no built-in "
                f"capability matches that name.",
                "",
                "  Available built-in capabilities:",
            ]
            if builtins:
                for cap in builtins:
                    desc = cap["description"]
                    line = f"    {cap['name']}"
                    if desc:
                        line += f"  — {desc}"
                    lines.append(line)
            else:
                lines.append("    (none found)")
            lines.extend([
                "",
                "  Try:",
                "    intent-os run translate -p text=... -p target_lang=zh",
                "",
                "  Or provide a path to a .yaml manifest:",
                f"    intent-os run examples/{manifest_ref}.yaml ...",
            ])
            print("\n".join(lines), file=sys.stderr)
            sys.exit(1)

    # ---- 2. Build input data -------------------------------------------
    input_data: dict[str, Any] = {}

    # 2a. --param / -p key=value [key=value ...]
    if args.param:
        for pair in args.param:
            if "=" not in pair:
                print(
                    f"Error: --param values must be key=value, got: {pair!r}",
                    file=sys.stderr,
                )
                sys.exit(1)
            key, _, val = pair.partition("=")
            # Try to interpret the value as JSON (number, bool, null, list, dict)
            # otherwise keep it as a plain string.
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass  # Not JSON — keep as plain string
            input_data[key.strip()] = val

    # 2b. --input / -i JSON string (overrides --param)
    if args.input:
        try:
            parsed = json.loads(args.input)
        except json.JSONDecodeError:
            parsed = {"text": args.input}
        if isinstance(parsed, dict):
            input_data.update(parsed)
        else:
            input_data["text"] = str(parsed)

    # 2c. --input-file / -f (overrides --input and --param)
    if args.input_file:
        try:
            file_data = json.loads(Path(args.input_file).read_text())
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            print(f"Error reading input file: {exc}", file=sys.stderr)
            sys.exit(1)
        if isinstance(file_data, dict):
            input_data.update(file_data)
        else:
            input_data["text"] = str(file_data)

    # 2d. Positional ``text`` argument (if manifest has a ``text`` input)
    if args.text and not input_data.get("text"):
        input_data["text"] = args.text

    # ---- 3. Set up executor --------------------------------------------
    executor = setup_executor()
    adapters = executor.get_available_adapters()

    # Fall back to simulated adapter when no real adapter is available
    if not adapters:
        from core.workflow_runner import SimulatedAdapter

        executor.register_adapter("simulated", SimulatedAdapter())
        adapters = ["simulated"]
        print("  Adapters loaded: simulated (no real runtime available)")
        print("  Install Ollama for real AI execution:")
        print("    https://ollama.com/download")
        print()

    adapter_name = args.adapter or adapters[0]
    if adapter_name not in executor._adapters:
        print(f"Error: Adapter '{adapter_name}' not loaded.", file=sys.stderr)
        if adapter_name == "ollama":
            print(file=sys.stderr)
            print("  [i] Ollama requires two things:", file=sys.stderr)
            print("     1. Install:   https://ollama.com/download", file=sys.stderr)
            print("     2. Start:     ollama serve", file=sys.stderr)
            print("     3. Pull model: ollama pull llama3.2:1b", file=sys.stderr)
            print(file=sys.stderr)
            print("  Check status:  curl http://localhost:11434/api/tags", file=sys.stderr)
        else:
            print(f"  Available: {', '.join(adapters)}", file=sys.stderr)
        sys.exit(1)

    print(f"\nExecuting '{manifest.id}' via '{adapter_name}'...")

    # ---- 4. Execute ----------------------------------------------------
    try:
        record = executor.execute(
            manifest=manifest,
            input_data=input_data,
            adapter_name=adapter_name,
        )
    except Exception as exc:
        print(f"\nExecution failed: {exc}", file=sys.stderr)
        err_str = str(exc).lower()
        if "connect" in err_str and "ollama" in err_str:
            print(file=sys.stderr)
            print("  [i] Make sure Ollama is running:", file=sys.stderr)
            print("     ollama serve", file=sys.stderr)
            print("     ollama pull llama3.2:1b", file=sys.stderr)
        elif "api key" in err_str:
            print(file=sys.stderr)
            print("  [i] Set your API key:", file=sys.stderr)
            if "openai" in err_str or "openai" in adapter_name:
                print("     export OPENAI_API_KEY=sk-...", file=sys.stderr)
            elif "anthropic" in err_str or "anthropic" in adapter_name:
                print("     export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
            elif "openrouter" in err_str or "openrouter" in adapter_name:
                print("     export OPENROUTER_API_KEY=...", file=sys.stderr)
            elif "github" in err_str or "github" in adapter_name:
                print("     export GITHUB_TOKEN=...", file=sys.stderr)
        sys.exit(1)

    display_record(record, args.output)

    try:
        context_id = getattr(args, "context", None)
        save_to_event_store(record, context_id=context_id)
    except Exception:
        pass  # Non-critical — execution results already displayed

    if args.save:
        save_path = save_execution_record(record, args.save)
        print(f"\nExecution record saved to: {save_path}")
