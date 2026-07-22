"""Intent OS CLI — run command."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any
from core.recorder import save_execution_record
from commands.helpers import load_manifest, setup_executor, save_to_event_store, display_record

def cmd_run(args: argparse.Namespace) -> None:
    manifest, _ = load_manifest(args.manifest)
    input_data = {}
    if args.input:
        try: input_data = json.loads(args.input)
        except json.JSONDecodeError: input_data = {"text": args.input}
    elif args.input_file:
        try: input_data = json.loads(Path(args.input_file).read_text())
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            print(f"Error reading input file: {exc}", file=sys.stderr); sys.exit(1)
    executor = setup_executor()
    adapters = executor.get_available_adapters()
    if not adapters:
        print("Error: No runtime adapters available.", file=sys.stderr)
        print(file=sys.stderr)
        print("  Install Ollama (free, local, no API key):", file=sys.stderr)
        print("    https://ollama.com/download", file=sys.stderr)
        print("    ollama pull llama3.2:1b", file=sys.stderr)
        print("    ollama serve", file=sys.stderr)
        print(file=sys.stderr)
        print("  Or set an API key:", file=sys.stderr)
        print("    export OPENAI_API_KEY=sk-...", file=sys.stderr)
        print(file=sys.stderr)
        sys.exit(1)
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
            print(f"Available: {', '.join(adapters)}", file=sys.stderr)
        sys.exit(1)
    print(f"\nExecuting '{manifest.id}' via '{adapter_name}'...")
    try:
        record = executor.execute(manifest=manifest, input_data=input_data, adapter_name=adapter_name)
    except Exception as exc:
        print(f"\nExecution failed: {exc}", file=sys.stderr)
        # Provide actionable follow-up tips for common failure modes
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
    try: save_to_event_store(record)
    except Exception: pass
    if args.save:
        save_path = save_execution_record(record, args.save)
        print(f"\nExecution record saved to: {save_path}")
