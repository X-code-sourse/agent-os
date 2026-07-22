"""Intent OS CLI — demo command.

Zero-configuration terminal demo that showcases Intent OS capabilities
without requiring any API keys, Ollama, or external dependencies.

Shows: validate → run → ask → security → registry search → quickstart
All output is simulated but accurate to actual command behavior.
"""

from __future__ import annotations

import sys
import time
from typing import Any


# ──────────────────────────────────────────────
# Demo script — steps with simulated output
# ──────────────────────────────────────────────


def _print_slow(text: str, delay: float = 0.003) -> None:
    """Print text with a typing-like effect."""
    for char in text:
        print(char, end="", flush=True)
        time.sleep(delay)
    print()


def _section(title: str) -> None:
    """Print a section header."""
    print()
    print(f"  {'=' * 55}")
    print(f"   {title}")
    print(f"  {'=' * 55}")
    print()


_DEMO_STEPS = [
    {
        "title": "Step 1: Validate a Capability Manifest",
        "command": "$ intent-os validate examples/translate.yaml",
        "output": [
            "[OK] Manifest 'translate@1.0.0' loaded successfully",
            "",
            "Manifest: translate@1.0.0",
            "Publisher: intent-os.org",
            "Input fields: ['text', 'source_lang', 'target_lang']",
            "Output fields: ['translated_text', 'detected_language']",
            "Security risk: low",
            "",
            "[OK] Manifest is valid",
        ],
        "explain": "A Capability Manifest describes what an AI capability does,\nwhat input it needs, and what output it produces — in a format\nthat any runtime can understand.",
    },
    {
        "title": "Step 2: Execute a capability",
        "command": "$ intent-os run examples/translate.yaml --adapter ollama \\",
        "command2": "    --input '{\"text\": \"Hello world\", \"target_lang\": \"zh\"}'",
        "output": [
            "[OK] Manifest 'translate@1.0.0' loaded successfully",
            "  Adapters loaded: ollama",
            "  Using local Ollama (free, no API key needed)",
            "",
            "Executing 'translate@1.0.0' via 'ollama'...",
            "",
            "============================================================",
            "EXECUTION RESULT",
            "============================================================",
            "  Status: success",
            "  Runtime: ollama via OllamaAdapter",
            "  Latency: 3215ms",
            "  Cost: $0.0000",
            "  Tokens: 187",
            "  Events: 3",
            "",
            "  Output:",
            '    translated_text: "你好世界"',
            '    detected_language: "en"',
            "",
            "  Event Sequence:",
            "    >> TaskStarted",
            "    -> CapabilityInvoked",
            "    OK TaskCompleted (3215ms)",
        ],
        "explain": "The same Manifest can run on ANY runtime — Ollama (local),\nOpenAI, Anthropic, or GitHub Models. No rewriting needed.",
    },
    {
        "title": "Step 3: Cross-runtime comparison",
        "command": "$ intent-os compare examples/translate.yaml \\",
        "command2": "    --input '{\"text\": \"Hello\", \"target_lang\": \"fr\"}'",
        "output": [
            "",
            "============================================================",
            "COMPARISON RESULTS",
            "============================================================",
            "",
            "openai vs ollama:",
            "  Schema compatible:          [OK]",
            "  Event structure match:      [OK]",
            "  Metric dimensions match:    [OK]",
            "",
            "  >>> Overall: COMPATIBLE",
            "",
            "METRICS COMPARISON",
            "  Metric           openai          ollama          ",
            "  -------------------------------------------------",
            "  Status           success         success         ",
            "  Latency (ms)     842             3215            ",
            "  Cost ($)         0.0018          0.0000          ",
            "  Tokens           95              187             ",
        ],
        "explain": "Compare latency, cost, and token usage across different\nruntimes — all from the same Manifest. Make data-driven\ndecisions about which runtime to use.",
    },
    {
        "title": "Step 4: Natural language with ask",
        "command": "$ intent-os ask \"translate 'good morning' to Japanese\"",
        "output": [
            "Intent OS -- Ask",
            '  Query: "translate \'good morning\' to Japanese"',
            "",
            "  Loading capability registry ...",
            "  Registry: ~/.intent-os/store.db",
            "  Capabilities registered: 8",
            "",
            "  Initialising LLM provider (auto)...",
            "  Using provider: openai (model: gpt-4o-mini)",
            "",
            "  Processing request ...",
            "",
            "  [OK] Translation completed: \"おはようございます\"",
            "",
            "  Execution details:",
            "    Status:  success",
            "    Runtime: openai",
            "    Latency: 1240ms",
            "    Cost:    $0.0021",
            "    Tokens:  156",
        ],
        "explain": "Zero technical knowledge needed. Just describe what you want\nin natural language. Intent OS finds or creates the right\ncapability and executes it.",
    },
    {
        "title": "Step 5: Security policy enforcement",
        "command": "$ intent-os security evaluate examples/code_review.yaml",
        "output": [
            "{",
            '  "capability_name": "code_review",',
            '  "decision": "allow",',
            '  "rationale": "Capability \'code_review\' has risk level \'low\'",',
            '  "policy_id": "dev-default",',
            '  "risk_level": "low"',
            "}",
        ],
        "explain": "Every capability has a declared risk level. The Security Manager\nevaluates each execution against organizational policies —\nauto-allow, require review, or block entirely.",
    },
    {
        "title": "Step 6: Semantic search in your capability registry",
        "command": "$ intent-os registry search \"code analysis\"",
        "output": [
            "Search results for 'code analysis' (2):",
            "  Score    Name                               Description",
            "  -----------------------------------------------------------------",
            "  0.8734  code_review@1.0.0                   Review code for issues",
            "  0.4215  text_summarize@1.0.0                Summarize text content",
        ],
        "explain": "No need to remember exact names. Semantic search finds\ncapabilities by what they DO, not what they're called.",
    },
]


def cmd_demo(args: Any) -> None:
    """Run an interactive terminal demo of Intent OS capabilities."""
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║            Intent OS — Interactive Demo              ║")
    print("  ║  Open interoperability for AI capabilities           ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    _print_slow("  This demo shows what Intent OS can do — no API keys")
    _print_slow("  or external services required. All output is simulated")
    _print_slow("  but accurately reflects real command behavior.")
    print()
    _print_slow("  Press Enter to start...")
    input()

    for step in _DEMO_STEPS:
        _section(step["title"])

        # Show the command
        _print_slow(f"  {step['command']}", delay=0.005)
        if "command2" in step:
            time.sleep(0.3)
            _print_slow(f"  {step['command2']}", delay=0.005)

        time.sleep(0.5)

        # Show the output line by line
        for line in step["output"]:
            time.sleep(0.08)
            _print_slow(f"  {line}", delay=0.002)

        time.sleep(0.5)

        # Show the explanation
        print()
        for explain_line in step["explain"].split("\n"):
            _print_slow(f"  → {explain_line}", delay=0.003)

        print()
        if step != _DEMO_STEPS[-1]:
            _print_slow("  Press Enter to continue...")
            input()

    # Closing
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║               Demo Complete                          ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    print("  Intent OS lets you:")
    print("    [1] Describe capabilities once — run anywhere")
    print("    [2] Compare runtimes by cost, speed, and quality")
    print("    [3] Compose capabilities into workflows (DAG)")
    print("    [4] Secure execution with policy-driven access control")
    print("    [5] Use natural language — no technical skills needed")
    print()
    print("  Ready to try it for real?")
    print("    pip install intent-os[all]")
    print("    export OPENAI_API_KEY=sk-...")
    print("    intent-os ask \"translate hello to French\"")
    print()
