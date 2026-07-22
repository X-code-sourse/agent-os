"""Intent OS — demo command: Agent Flight Recorder showcase.

Zero-configuration terminal demo that shows what Agent Flight Recorder
does — no API keys, Ollama, or external dependencies required.

The demo simulates a coding agent execution and shows the trace output,
creating the "aha" moment: "I didn't know I could see what my agent did."
"""

from __future__ import annotations

import sys
import time
from typing import Any


def _print_slow(text: str, delay: float = 0.003) -> None:
    for char in text:
        print(char, end="", flush=True)
        time.sleep(delay)
    print()


def _section(title: str) -> None:
    print()
    print(f"  {'=' * 50}")
    print(f"   {title}")
    print(f"  {'=' * 50}")
    print()


def cmd_demo(args: Any) -> None:
    """Run the Agent Flight Recorder demo.

    When ``--auto`` is passed, the demo runs end-to-end without waiting
    for any interactive input.
    """
    auto = getattr(args, "auto", False)

    print()
    print("  ================================================")
    print("    Agent Flight Recorder - Interactive Demo")
    print("  ================================================")
    print()
    _print_slow("  See what your AI coding agent really does behind the scenes.")
    _print_slow("  No API keys or external services required.")
    print()

    if not auto:
        _print_slow("  Press Enter to start...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            return
    else:
        _print_slow("  Starting demo...")
        time.sleep(0.5)

    # ── Scene: coding agent execution ──
    _section("Your coding agent receives a task")

    _print_slow("  Task: Refactor authentication module to use JWT")
    print()
    time.sleep(0.3)

    # Step through the execution
    steps = [
        ("Planning", "Planner created workflow with 4 steps", 0.3),
        ("Reading", "Read files: auth.py, config.py, requirements.txt", 0.4),
        ("Model", "Called Claude Sonnet 4 (prompt: 2,451 tokens)", 0.5),
        ("Writing", "Modified auth.py (+89 lines, -23 lines)", 0.4),
        ("Testing", "Ran pytest tests/test_auth.py", 0.5),
        ("Result", "Tests failed: 2 passed, 1 failed", 0.3),
    ]

    for icon, desc, delay in steps:
        _print_slow(f"    [{icon}] {desc}", delay=0.004)
        time.sleep(delay)

    # ── The "aha" moment ──
    print()
    _print_slow("  What just happened? Your agent ran 6 steps, called an AI model,")
    _print_slow("  modified files, ran tests, and failed. But you saw none of it.")
    print()
    time.sleep(0.8)

    # ── Show the trace ──
    _section("Agent Flight Recorder - Trace")

    _print_slow("  $ intent-os inspect latest")
    print()

    trace_lines = [
        "  ================================================",
        "    Agent Flight Recorder - Execution Trace",
        "  ================================================",
        "",
        "  [OK]  Goal:        refactor-auth-to-jwt",
        "     Version:    1.0.0",
        "     Runtime:    anthropic (AnthropicAdapter)",
        "     Duration:   14,327ms",
        "     Cost:       $0.0842",
        "     Tokens:     4,891",
        "     Error:      Tests failed: 2 passed, 1 failed",
        "",
        "  -- Timeline (6 events) --",
        "",
        "  [14:02:01] > START (planner) refactor-auth-to-jwt",
        "  [14:02:02] > INVOKE (adapter) refactor-auth-to-jwt",
        "  [14:02:05] > START step=read-files",
        "  [14:02:06] > INVOKE (adapter) read-files -- 2451 tokens",
        "  [14:02:08] OK DONE  read-files (3241ms)",
        "  [14:02:08] > START step=modify-auth",
        "  [14:02:09] > INVOKE (adapter) modify-auth -- model=claude-sonnet-4",
        "  [14:02:14] OK DONE  modify-auth (5824ms)",
        "  [14:02:14] > START step=run-tests",
        "  [14:02:15] > INVOKE (adapter) run-tests",
        "  [14:02:27] !! FAIL  run-tests (12713ms) -- reason=\"test_jwt_verify failed\"",
        "",
        "  Trace ID: abc123-def456-ghi789",
    ]

    for line in trace_lines:
        _print_slow(f"  {line}" if line.startswith("  ") else line, delay=0.002)
        time.sleep(0.04)

    print()

    # ── Key insight ──
    _section("What you get")

    insights = [
        ("Full visibility", "See every step your agent took - tools, models, files"),
        ("Failure analysis", "Know exactly why and where your agent failed"),
        ("Cost tracking", "Every call tracked: tokens, latency, total cost"),
        ("Shareable traces", "Export traces as HTML to share with your team"),
    ]

    for icon, desc in insights:
        _print_slow(f"  [{icon}] {desc}", delay=0.005)
        time.sleep(0.2)
    print()

    time.sleep(0.5)

    # ── HTML export demo ──
    _section("Export trace as HTML")

    _print_slow("  $ intent-os inspect latest --html")
    _print_slow("  Trace exported to intent-os-trace-abc123-def456.html")
    _print_slow("  Open in browser: file:///.../intent-os-trace-abc123-def456.html")
    print()
    _print_slow("  One file. No server. No cloud. Just the trace.")
    print()

    # ── Closing ──
    time.sleep(0.5)
    print()
    print("  ================================================")
    print("    Demo Complete")
    print("  ================================================")
    print()
    _print_slow("  Your AI coding agent is a black box.")
    _print_slow("  Agent Flight Recorder opens it.")
    print()
    _print_slow("  Install:  pip install intentos")
    _print_slow("  Run:      intent-os demo --auto")
    _print_slow("  Docs:     https://intent-os.org")
    print()

    if not auto:
        _print_slow("  Press Enter to exit...")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
