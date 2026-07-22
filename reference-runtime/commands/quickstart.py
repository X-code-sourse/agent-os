"""Intent OS CLI — quickstart command.

Guides new users through their first Intent OS experience:
install → validate → run → compare.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_STEPS = {
    "ollama": {
        "title": "1. Install Ollama (free, local inference)",
        "lines": [
            "   Download: https://ollama.com/download",
            "   Pull a model:  ollama pull llama3.2:1b",
            "   Start server:  ollama serve",
        ],
    },
    "adapter": {
        "title": "2. Check runtime adapters",
        "lines": [
            "   Run:  intent-os list",
            "   Expected output shows available adapter(s).",
            "   If none: install Ollama (step 1) or set OPENAI_API_KEY.",
        ],
    },
    "validate": {
        "title": "3. Validate a Capability Manifest",
        "lines": [
            "   Run:  intent-os validate examples/text_summarize.yaml",
            "   Expected: 'Manifest is valid'",
            "   A Manifest describes what a capability does and what it needs.",
        ],
    },
    "run": {
        "title": "4. Execute a capability",
        "lines": [
            "   Run:  intent-os run examples/text_summarize.yaml \\",
            "           --adapter ollama \\",
            "           --input '{\"text\": \"AI is transforming the world.\"}'",
            "   Expected: an Execution Record with summary output.",
        ],
    },
    "compare": {
        "title": "5. Cross-runtime comparison (Phase 0 core test)",
        "lines": [
            "   Run:  intent-os compare examples/text_summarize.yaml \\",
            "           --input '{\"text\": \"Hello world\"}'",
            "   Compares execution records across all loaded adapters.",
        ],
    },
    "workflow": {
        "title": "6. Plan and run a workflow",
        "lines": [
            "   Plan:  intent-os workflow plan \"research AI trends\"",
            "   Run:   intent-os workflow run examples/research_workflow.yaml \\",
            "            --input '{\"company_name\": \"NVIDIA\", \"ticker\": \"NVDA\"}'",
            "   Workflows compose multiple capabilities into a DAG.",
        ],
    },
    "registry": {
        "title": "7. Register and discover capabilities",
        "lines": [
            "   Register:  intent-os registry register examples/text_summarize.yaml",
            "   List:      intent-os registry list",
            "   A persistent registry stores capabilities for reuse.",
        ],
    },
}


def cmd_quickstart(args: Any) -> None:
    """Display a step-by-step getting-started guide."""
    print()
    print("  ==========================================================")
    print("       Intent OS -- 5-Minute Quickstart")
    print("       Open interoperability for AI capabilities")
    print("  ==========================================================")
    print()

    for step_key in ["ollama", "adapter", "validate", "run", "compare", "workflow", "registry"]:
        step = _STEPS[step_key]
        print(f"  {step['title']}")
        for line in step["lines"]:
            print(f"  {line}")
        print()

    # Quick check: detect Ollama availability
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        resp = urllib.request.urlopen(req, timeout=1)
        if resp.status == 200:
            print("  [OK] Ollama is running -- ready for local execution!")
        else:
            print("  [!!] Ollama server not available. See step 1.")
    except Exception:
        print("  [!!] Ollama server not detected. Install & start for free local execution.")

    print()
    print("  Need help?")
    print("    Read the docs:   specs/SPEC-0001-capability-manifest.md")
    print("    Visit:           https://github.com/X-code-sourse/intentos")
    print()
