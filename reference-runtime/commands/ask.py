"""
Intent OS — CLI Command: ask

Natural-language capability invocation: classify intent, resolve or generate a
manifest, extract parameters, execute, and summarise the result.

Supports both single-query mode (``intent-os ask "..."``) and interactive
multi-turn REPL mode (``intent-os ask`` with no arguments).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from commands.helpers import get_registry_store, setup_executor

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# Adapter-switch keyword map
# ---------------------------------------------------------------------------

_ADAPTER_KEYWORDS: dict[str, list[str]] = {
    "openai": ["openai", "open ai"],
    "anthropic": ["anthropic", "claude"],
    "ollama": ["ollama", "llama"],
    "openrouter": ["openrouter"],
    "github_models": ["github models", "github"],
}


def _detect_adapter_switch(text: str) -> str | None:
    """Detect whether the user is asking to switch runtime adapters.

    Supports Chinese (``用 OpenAI``) and English (``use openai``,
    ``switch to openai``) patterns.

    Returns the canonical adapter name (e.g. ``"openai"``) or *None*.
    """
    text_lower = text.lower().strip()

    for adapter, keywords in _ADAPTER_KEYWORDS.items():
        for kw in keywords:
            kw_escaped = re.escape(kw).replace(r"\ ", r"\s*")

            # Chinese: 用 OpenAI, 用OpenAI, 用 openai, 用 openai
            if re.search(r"用\s*" + kw_escaped, text, re.IGNORECASE):
                return adapter

            # English: use openai, switch to openai, change to openai
            if re.search(
                rf"(?<!\w)(?:use|switch\s+to|change\s+to)\s+{re.escape(kw)}(?!\w)",
                text_lower,
            ):
                return adapter

    return None


def _print_execution_details(record: dict[str, Any] | None) -> None:
    """Print execution details from a result record dict.

    Handles both the flat key format (``runtime_id``, ``total_latency_ms`` …)
    used by the original single-query output, and the nested format produced
    by :meth:`ExecutionRecord.to_dict`.
    """
    if not record or not isinstance(record, dict):
        return

    # Support nested (to_dict style) and flat keys
    def _nested_or_flat(*path: str) -> Any:
        val: Any = record
        for key in path:
            if isinstance(val, dict):
                val = val.get(key, ...)
            else:
                return ...
        return val

    status = _nested_or_flat("status")
    runtime = _nested_or_flat("runtime", "id")
    if runtime is ...:
        runtime = record.get("runtime_id", "?")
    adapter = _nested_or_flat("runtime", "adapter")
    if adapter is ...:
        adapter = record.get("adapter", "?")

    latency = _nested_or_flat("metrics", "total_latency_ms")
    if latency is ...:
        latency = record.get("total_latency_ms", "?")
    cost = _nested_or_flat("metrics", "total_cost_usd")
    if cost is ...:
        cost = record.get("total_cost_usd", "?")
    tokens = _nested_or_flat("metrics", "total_tokens")
    if tokens is ...:
        tokens = record.get("total_tokens", "?")

    print("  Execution details:")
    print(f"    Status:  {status}")
    print(f"    Runtime: {runtime}")
    print(f"    Adapter: {adapter}")
    if isinstance(latency, (int, float)):
        print(f"    Latency: {latency:.0f}ms")
    else:
        print(f"    Latency: {latency}")
    if isinstance(cost, (int, float)):
        print(f"    Cost:    ${cost:.4f}")
    else:
        print(f"    Cost:    {cost}")
    print(f"    Tokens:  {tokens}")
    print()


def _display_result(result: Any, session: Any = None) -> bool:
    """Display an AskResult matching the single-query mode's output style.

    When *session* is provided and the result created a manifest, the user
    is prompted interactively to save it.

    Returns ``True`` when the result indicates success.
    """
    if result.error:
        print(f"  Error: {result.error}")
        return False

    print(f"  {'[OK]' if result.success else '[!]'} {result.summary}")
    print()

    if result.manifest_created and session and session.pending_manifest_yaml:
        yaml_text = session.pending_manifest_yaml
        print("  I created a new capability to handle your request:")
        print()
        for line in (yaml_text or "").strip().split("\n")[:10]:
            print(f"    {line}")
        if yaml_text and len(yaml_text.split("\n")) > 10:
            print("    ...")
        print()
        print("  Save this capability for future use?")
        try:
            answer = input("  [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            if session.confirm_and_register():
                print("  [OK] Saved! You can reuse it anytime.")
            else:
                print("  [!] Failed to save.")
        else:
            print("  [i] Not saved. I'll generate it again next time you ask.")
        print()

    _print_execution_details(result.record)

    return result.success


def _interactive_mode(
    registry: Any,
    executor: Any,
    provider: Any,
    db_path: Path,
    capabilities: list[dict[str, Any]],
) -> None:
    """Multi-turn interactive REPL for the Ask command.

    Each line of input is processed through a fresh :class:`AskSession`.
    Context from the previous turn (last intent, last manifest name, last
    input parameters) is tracked so that adapter-switch commands like
    ``"用 OpenAI"`` can re-execute the same capability through a different
    runtime adapter without re-classifying the intent.
    """
    print()
    print("Intent OS Ask — interactive mode (type 'exit' to quit)")
    print()

    from core.ask import AskSession, AskResult

    # -- context tracking for adapter switching ----------------------------
    last_raw: str | None = None
    last_manifest_name: str | None = None
    last_params: dict[str, Any] = {}

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw.lower() in ("exit", "quit"):
            break

        # -- detect adapter switch -----------------------------------------
        adapter_name = _detect_adapter_switch(raw)

        # Create a fresh session for every turn so that LLM calls are
        # independent (no prompt-history bleed between unrelated requests).
        session = AskSession(
            registry=registry,
            executor=executor,
            llm_provider=provider,
        )

        # -- adapter switch: reuse last capability -------------------------
        if adapter_name is not None and last_manifest_name is not None and last_raw is not None:
            manifest = registry.get(last_manifest_name)
            if manifest is not None:
                try:
                    record = executor.execute(
                        manifest=manifest,
                        input_data=last_params,
                        adapter_name=adapter_name,
                    )

                    # Generate a natural-language summary via the session's
                    # LLM summariser (same code path as single-query mode).
                    summary = session._summarize(record)

                    result = AskResult(
                        success=record.status.value == "success",
                        summary=summary,
                        record=record.to_dict() if hasattr(record, "to_dict") else {},
                        manifest_created=False,
                        error=record.error,
                    )
                    _display_result(result)
                    continue
                except Exception as exc:
                    print(f"  Adapter switch failed: {exc}")
                    print()
                    continue

        # -- normal processing ---------------------------------------------
        result = session.process(raw)
        ok = _display_result(result, session)

        # Persist context for future adapter-switch commands.
        if ok and not result.error:
            last_raw = raw
            if result.record and isinstance(result.record, dict):
                # Record may use nested (to_dict) or flat key layout.
                manifest_info = result.record.get("manifest", {})
                if isinstance(manifest_info, dict):
                    last_manifest_name = manifest_info.get("name")
                else:
                    last_manifest_name = result.record.get("manifest_name")

                input_data = result.record.get("input")
                if isinstance(input_data, dict):
                    last_params = dict(input_data)
                else:
                    last_params = {}


# ===================================================================
# Entry point
# ===================================================================


def cmd_ask(args: Any) -> None:
    """Process a natural-language query: classify, execute, and summarise.

    Behaviour depends on whether a positional *query* argument is given:

    * **With a query** (``intent-os ask "…"``) — single-request mode.
      Classifies the intent, resolves or generates a manifest, extracts
      parameters, executes, summarises, and (when a manifest was generated)
      asks the user whether to persist it.

    * **Without a query** (``intent-os ask``) — interactive multi-turn REPL.
      See :func:`_interactive_mode` for details.
    """
    # -- resolve the query string -------------------------------------------
    query = args.query

    if not query or not query.strip():
        # -- interactive REPL mode ------------------------------------------
        from core.llm_provider import ProviderFactory
        from core.ask import AskSession

        print("Intent OS — Ask")
        print()

        print("  Loading capability registry ...")
        db_path, registry = get_registry_store()
        capabilities = registry.list_capabilities()
        print(f"  Registry: {db_path}")
        print(f"  Capabilities registered: {len(capabilities)}")

        # -- LLM provider ---------------------------------------------------
        print()
        print("  Initialising LLM provider (auto)...")

        try:
            provider = ProviderFactory.create("auto")
        except RuntimeError as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            print()
            print("  Install Ollama (free, local, no API key):")
            print("    https://ollama.com/download")
            print("    ollama pull llama3.2:1b")
            print("    ollama serve")
            print()
            print("  Or set an API key:")
            print("    export OPENAI_API_KEY=sk-...")
            print("    export ANTHROPIC_API_KEY=sk-ant-...")
            print()
            sys.exit(1)

        print(f"  Using provider: {provider.name} (model: {provider.model})")

        # -- executor -------------------------------------------------------
        print()
        print("  Loading runtime adapters ...")
        executor = setup_executor()

        available = executor.get_available_adapters()
        if not available:
            print()
            print("  [i] No adapters are available. The Ask session will still")
            print("      classify and generate manifests, but execution will fail.")
            print("      See the adapter setup instructions above.")

        _interactive_mode(registry, executor, provider, db_path, capabilities)
        return

    query = query.strip()

    # -- single-query mode (original flow, unchanged) -----------------------
    print("Intent OS — Ask")
    print(f'  Query: "{query}"')
    print()

    # -- lazy imports -------------------------------------------------------
    from core.llm_provider import ProviderFactory
    from core.ask import AskSession

    # -- registry -----------------------------------------------------------
    print("  Loading capability registry ...")
    db_path, registry = get_registry_store()
    capabilities = registry.list_capabilities()
    print(f"  Registry: {db_path}")
    print(f"  Capabilities registered: {len(capabilities)}")

    # -- LLM provider -------------------------------------------------------
    print()
    print("  Initialising LLM provider (auto)...")

    try:
        provider = ProviderFactory.create("auto")
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        print()
        print("  Install Ollama (free, local, no API key):")
        print("    https://ollama.com/download")
        print("    ollama pull llama3.2:1b")
        print("    ollama serve")
        print()
        print("  Or set an API key:")
        print("    export OPENAI_API_KEY=sk-...")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        print()
        sys.exit(1)

    print(f"  Using provider: {provider.name} (model: {provider.model})")

    # -- executor -----------------------------------------------------------
    print()
    print("  Loading runtime adapters ...")
    executor = setup_executor()

    available = executor.get_available_adapters()
    if not available:
        print()
        print("  [i] No adapters are available. The Ask session will still")
        print("      classify and generate manifests, but execution will fail.")
        print("      See the adapter setup instructions above.")

    # -- AskSession ---------------------------------------------------------
    print()
    print("  Processing request ...")
    print()

    session = AskSession(
        registry=registry,
        executor=executor,
        llm_provider=provider,
    )

    result = session.process(query)

    # -- output -------------------------------------------------------------
    if result.error:
        print(f"  Error: {result.error}", file=sys.stderr)
        sys.exit(1)

    print(f"  {'[OK]' if result.success else '[!]'} {result.summary}")
    print()

    if result.manifest_created:
        yaml_text = session.pending_manifest_yaml
        print("  I created a new capability to handle your request:")
        print()
        for line in (yaml_text or "").strip().split("\n")[:10]:
            print(f"    {line}")
        if yaml_text and len(yaml_text.split("\n")) > 10:
            print("    ...")
        print()
        print("  Save this capability for future use?")
        try:
            answer = input("  [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            if session.confirm_and_register():
                print("  [OK] Saved! You can reuse it anytime with:")
                print(f'    intent-os ask "{query}"')
            else:
                print("  [!] Failed to save.")
        else:
            print("  [i] Not saved. I'll generate it again next time you ask.")
        print()

    if result.record and isinstance(result.record, dict):
        status = result.record.get("status", "?")
        runtime = result.record.get("runtime_id", "?")
        adapter = result.record.get("adapter", "?")
        latency = result.record.get("total_latency_ms", "?")
        cost = result.record.get("total_cost_usd", "?")
        tokens = result.record.get("total_tokens", "?")

        print("  Execution details:")
        print(f"    Status:  {status}")
        print(f"    Runtime: {runtime}")
        print(f"    Adapter: {adapter}")
        print(
            f"    Latency: {latency}ms"
            if isinstance(latency, (int, float))
            else f"    Latency: {latency}"
        )
        print(
            f"    Cost:    ${cost:.4f}"
            if isinstance(cost, (int, float))
            else f"    Cost:    {cost}"
        )
        print(f"    Tokens:  {tokens}")
        print()

    if not result.success:
        sys.exit(1)
