"""
Intent OS — CLI Command: compare

Executes the same capability on two adapters and compares results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from core.recorder import compare_records, save_execution_record
from commands.helpers import load_manifest, setup_executor, save_to_event_store, print_table

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def cmd_compare(args: Any) -> None:
    """
    Execute the same capability on two adapters and compare results.
    """
    manifest, _ = load_manifest(args.manifest)

    # Parse input
    input_data: dict[str, Any] = {}
    if args.input:
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError:
            input_data = {"text": args.input}

    # Build executor
    executor = setup_executor()
    adapters = executor.get_available_adapters()

    if len(adapters) < 2:
        print(
            "Warning: Comparison needs at least 2 adapters loaded. "
            "Install Ollama (free) or set up API keys for multiple runtimes.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("  To compare OpenAI ↔ Ollama:", file=sys.stderr)
        print("    1. Install Ollama: https://ollama.com/download", file=sys.stderr)
        print("    2. ollama pull llama3.2:1b", file=sys.stderr)
        print("    3. ollama serve", file=sys.stderr)
        print("    4. export OPENAI_API_KEY=sk-...", file=sys.stderr)
        print("    5. intent-os compare <manifest> --input '...'", file=sys.stderr)
        print(file=sys.stderr)

    records = []
    for adapter_name in adapters:
        print(f"\n{'='*60}")
        print(f"Executing on '{adapter_name}'...")
        try:
            record = executor.execute(
                manifest=manifest,
                input_data=input_data,
                adapter_name=adapter_name,
            )
            records.append((adapter_name, record))
            print(f"  Status: {record.status.value}")
            print(f"  Latency: {record.total_latency_ms:.0f}ms")
            print(f"  Cost: ${record.total_cost_usd:.4f}")
            print(f"  Tokens: {record.total_tokens}")
        except Exception as exc:
            print(f"  FAILED: {exc}")

    # Compare if we have at least 2 records
    if len(records) >= 2:
        from core.recorder import compare_records

        print(f"\n{'='*60}")
        print("COMPARISON RESULTS")
        print(f"{'='*60}")

        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                name_a, rec_a = records[i]
                name_b, rec_b = records[j]
                result = compare_records(rec_a, rec_b)

                print(f"\n{name_a} vs {name_b}:")
                print(f"  Schema compatible: "
                      f"[{'OK' if result['checks']['schema_compatibility']['passed'] else 'FAIL'}]")
                print(f"  Event structure match: "
                      f"[{'OK' if result['checks']['event_structure_match']['passed'] else 'FAIL'}]")
                print(f"  Metric dimensions match: "
                      f"[{'OK' if result['checks']['metric_dimensions_match']['passed'] else 'FAIL'}]")

                detail = result['checks']['metric_dimensions_match']['details']
                if detail.get('missing_in_b') or detail.get('missing_in_a'):
                    print(f"   - Missing in {name_b}: {detail['missing_in_b']}")
                    print(f"   - Missing in {name_a}: {detail['missing_in_a']}")

                verdict = "COMPATIBLE" if result['compatible'] else "NOT COMPATIBLE"
                print(f"\n  >>> Overall: {verdict}")

        # Also show side-by-side metrics
        print(f"\n{'='*60}")
        print("METRICS COMPARISON")
        print(f"{'='*60}")
        headers = ["Metric"] + [r[0] for r in records]
        rows = [
            ("Status", [r[1].status.value for r in records]),
            ("Latency (ms)", [f"{r[1].total_latency_ms:.0f}" for r in records]),
            ("Cost ($)", [f"{r[1].total_cost_usd:.4f}" for r in records]),
            ("Tokens", [str(r[1].total_tokens) for r in records]),
        ]
        print_table(headers, rows)

    # Auto-save all records to Event Store
    for _, record in records:
        try:
            save_to_event_store(record)
        except Exception:
            pass  # Non-critical — comparison results are already displayed

    # Save records
    if args.save:
        from core.recorder import save_execution_record
        for adapter_name, record in records:
            save_path = Path(args.save) / f"{adapter_name}_record.json"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_execution_record(record, save_path)
            print(f"  Record saved: {save_path}")
