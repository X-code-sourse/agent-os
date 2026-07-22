"""
Intent OS — Ask Command End-to-End Integration Tests

Conditionally-skipped tests that connect to a real LLM provider (Ollama, OpenAI, or
Anthropic) to verify the full Ask pipeline: classify, resolve manifest, extract params,
execute, and summarise.

When no LLM provider is available all tests are skipped with:

    [skip] no LLM provider available

Pattern follows ``test_cross_runtime.py``: a module-level detection function sets a
module constant that each ``@pytest.mark.skipif`` uses.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.ask import AskSession, PreferencesStore
from core.executor import Executor
from core.llm_provider import ProviderFactory
from core.parser import parse_manifest
from core.registry import CapabilityRegistry
from core.workflow_runner import SimulatedAdapter


# ---------------------------------------------------------------------------
# Provider detection (module level — mirrors test_cross_runtime.py)
# ---------------------------------------------------------------------------

def _provider_available() -> bool:
    """Return True if any LLM provider can be created (Ollama, OpenAI, or Anthropic).

    Mirrors the ``_ollama_available()`` pattern in ``test_cross_runtime.py`` but
    checks all providers by delegating to ``ProviderFactory.create("auto")``.
    """
    try:
        ProviderFactory.create("auto")
        return True
    except RuntimeError:
        return False
    except Exception:
        return False


PROVIDER_AVAILABLE: bool = _provider_available()

_PROVIDER_NAME: str | None = None
if PROVIDER_AVAILABLE:
    try:
        _PROVIDER_NAME = ProviderFactory.create("auto").name
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEXT_SUMMARIZE_PATH: Path = _project_root / "examples" / "text_summarize.yaml"
"""Path to the text_summarize capability manifest used by most tests."""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def text_summarize_manifest():
    """Parse and return the text_summarize.yaml capability manifest."""
    manifest, result = parse_manifest(TEXT_SUMMARIZE_PATH)
    assert result.valid, (
        f"text_summarize.yaml is invalid: "
        f"{[e.message for e in result.errors]}"
    )
    return manifest


@pytest.fixture
def empty_registry() -> CapabilityRegistry:
    """An in-memory CapabilityRegistry with no capabilities registered."""
    return CapabilityRegistry(db_path=None)


@pytest.fixture
def registry_with_summarize(text_summarize_manifest) -> CapabilityRegistry:
    """A registry with text_summarize pre-registered (in-memory, no persistence)."""
    registry = CapabilityRegistry(db_path=None)
    registry.register(text_summarize_manifest)
    assert registry.count() == 1
    return registry


@pytest.fixture
def executor_with_simulated() -> Executor:
    """An Executor with a single SimulatedAdapter registered — no real API calls."""
    exe = Executor()
    exe.register_adapter("simulated", SimulatedAdapter(name="simulated"))
    return exe


@pytest.fixture
def provider() -> Any:
    """A real LLM provider instance (skips the test when unavailable)."""
    if not PROVIDER_AVAILABLE:
        pytest.skip("[skip] no LLM provider available")
    return ProviderFactory.create("auto")


def _make_session(
    registry: CapabilityRegistry,
    executor: Executor,
    llm: Any,
    tmp_dir: Path,
    name: str = "ask_e2e.db",
) -> AskSession:
    """Build an AskSession following the pattern from ``test_ask.py``.

    Uses a ``PreferencesStore`` backed by the given ``tmp_dir`` for DB isolation
    between tests.
    """
    return AskSession(
        registry=registry,
        executor=executor,
        llm_provider=llm,
        preferences=PreferencesStore(db_path=str(tmp_dir / name)),
    )


# ====================================================================
# Test 1: ask "summarize this text" matches text_summarize
# ====================================================================


@pytest.mark.ask_e2e
class TestAskMatchesExistingCapability:
    """The Ask pipeline correctly identifies and executes a registered capability."""

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_ask_matches_text_summarize(
        self,
        registry_with_summarize: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """``ask "summarize this text"`` resolves to the registered text_summarize
        capability and executes successfully.

        The LLM classifies the intent, the registry lookup finds the pre-registered
        manifest, and the SimulatedAdapter produces a deterministic output that
        validates against the manifest schema.
        """
        session = _make_session(
            registry_with_summarize,
            executor_with_simulated,
            provider,
            tmp_path,
        )

        result = session.process(
            "summarize this text: The quick brown fox jumps over the lazy dog. "
            "This is a simple test sentence for summarization that demonstrates "
            "the text summarization capability."
        )

        # The pipeline ran without exceptions
        assert result.error is None, f"Process returned error: {result.error}"

        # Execution should have succeeded (SimulatedAdapter + schema match)
        assert result.success is True, (
            f"Expected successful execution, got status from record: "
            f"{result.record.get('status', '?' )}"
        )

        # The manifest should have been looked up from the registry, not generated
        assert result.manifest_created is False, (
            "Expected to match existing text_summarize manifest, "
            "but a new one was generated instead"
        )

        # The execution record must reference text_summarize
        record = result.record
        assert isinstance(record, dict), (
            f"Expected dict record, got {type(record).__name__}"
        )
        manifest_info = record.get("manifest", {})
        assert manifest_info.get("name") == "text_summarize", (
            f"Expected manifest name 'text_summarize', "
            f"got {manifest_info.get('name')!r}"
        )

        # The output should contain the summary field
        output = record.get("output", {})
        assert isinstance(output, dict), (
            f"Expected dict output, got {type(output).__name__}"
        )
        assert "summary" in output, (
            f"Output should contain a 'summary' field, got keys: {list(output.keys())}"
        )
        assert isinstance(output["summary"], str), (
            f"Expected string summary, got {type(output['summary']).__name__}"
        )
        assert len(output["summary"]) > 0, "Summary should not be empty"

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_summary_is_readable(
        self,
        registry_with_summarize: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """The AskResult summary is a non-empty, readable sentence
        produced by the LLM summarisation step."""
        session = _make_session(
            registry_with_summarize,
            executor_with_simulated,
            provider,
            tmp_path,
        )

        result = session.process(
            "summarize this text: Artificial intelligence is transforming "
            "how we interact with computers. This text covers the basics "
            "of natural language processing and machine learning."
        )

        assert result.error is None, f"Process returned error: {result.error}"
        assert result.summary, "Summary should be non-empty"
        assert len(result.summary) > 10, (
            f"Summary is too short ({len(result.summary)} chars): {result.summary!r}"
        )
        # The summary should end with a sentence-ending character
        assert result.summary.strip()[-1] in (".", "!", "?"), (
            f"Summary should end with sentence-ending punctuation: {result.summary!r}"
        )


# ====================================================================
# Test 2: ask something that generates a new manifest, then confirm
# ====================================================================


@pytest.mark.ask_e2e
class TestAskGeneratesNewManifest:
    """When no registered capability matches, the LLM generates a new manifest
    which the user can then confirm and register."""

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_generates_new_manifest_and_confirm(
        self,
        empty_registry: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """An unrecognised request causes the LLM to generate a fresh manifest.

        After generation the pending YAML is available, and calling
        ``confirm_and_register()`` persists it to the registry.
        """
        session = _make_session(
            empty_registry,
            executor_with_simulated,
            provider,
            tmp_path,
        )

        # Pick a request that is unlikely to exist in the (empty) registry
        result = session.process(
            "translate 'hello' to Spanish"
        )

        # The pipeline ran without an exception
        assert result.error is None, f"Process returned error: {result.error}"

        # A new manifest should have been generated (because the registry is empty)
        assert result.manifest_created is True, (
            "Expected a new manifest to be generated since the registry is empty"
        )

        # There must be pending YAML for user confirmation
        pending = session.pending_manifest_yaml
        assert pending is not None, "Expected pending manifest YAML after generation"
        assert len(pending.strip()) > 0, "Pending manifest YAML should not be empty"

        # The pending YAML should parse as a valid capability
        parsed_manifest, parse_result = parse_manifest(pending)
        assert parse_result.valid, (
            f"Generated manifest is invalid: "
            f"{[e.message for e in parse_result.errors]}"
        )
        assert parsed_manifest.name is not None and len(parsed_manifest.name) > 0

        # Confirm and register
        assert session.confirm_and_register() is True, (
            "confirm_and_register() should return True after generation"
        )

        # Pending YAML must be cleared after confirmation
        assert session.pending_manifest_yaml is None, (
            "Pending manifest should be cleared after confirmation"
        )

        # The registry should now contain exactly one capability
        assert empty_registry.count() == 1, (
            f"Expected 1 registered capability, got {empty_registry.count()}"
        )

        # The registered capability should match the generated one
        registered = empty_registry.get(parsed_manifest.name)
        assert registered is not None, (
            f"Capability '{parsed_manifest.name}' should be findable in the registry"
        )
        assert registered.name == parsed_manifest.name
        assert registered.version == parsed_manifest.version

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_double_confirm_returns_false(
        self,
        empty_registry: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """Calling ``confirm_and_register`` a second time returns ``False``
        because the pending manifest was already consumed."""
        session = _make_session(
            empty_registry,
            executor_with_simulated,
            provider,
            tmp_path,
        )

        result = session.process("create a todo list for today")

        assert result.manifest_created is True
        assert session.pending_manifest_yaml is not None

        # First confirmation should succeed
        assert session.confirm_and_register() is True

        # Second confirmation should fail (nothing pending)
        assert session.confirm_and_register() is False

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_confirm_without_pending_returns_false(
        self,
        empty_registry: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """Calling ``confirm_and_register`` when no manifest was generated
        returns ``False``."""
        session = _make_session(
            empty_registry,
            executor_with_simulated,
            provider,
            tmp_path,
        )
        assert session.pending_manifest_yaml is None
        assert session.confirm_and_register() is False


# ====================================================================
# Test 3: ask with --provider (verify switching)
# ====================================================================


@pytest.mark.ask_e2e
class TestAskProviderSwitching:
    """The system correctly uses different LLM provider instances."""

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_auto_provider_has_correct_name(
        self,
        provider: Any,
    ) -> None:
        """The auto-detected provider exposes the correct name attribute."""
        assert provider.name is not None
        assert isinstance(provider.name, str)
        assert len(provider.name) > 0
        # Provider name is one of the known values
        assert provider.name in ("ollama", "openai", "anthropic", "auto"), (
            f"Unexpected provider name: {provider.name!r}"
        )
        # 'auto' should never be the resolved name since AutoProvider delegates
        assert provider.name != "auto", (
            "AutoProvider should delegate to a concrete provider, not itself"
        )

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_explicit_provider_creation(
        self,
        registry_with_summarize: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """An explicit provider (same type as auto-detected) can be created
        and used to process requests identically."""
        provider_name = provider.name

        # Create an explicit provider of the same type
        explicit_provider = ProviderFactory.create(provider_name)

        assert explicit_provider.name == provider_name, (
            f"Explicit provider name {explicit_provider.name!r} "
            f"should match auto-detected {provider_name!r}"
        )

        session = _make_session(
            registry_with_summarize,
            executor_with_simulated,
            explicit_provider,
            tmp_path,
            name="explicit.db",
        )

        result = session.process(
            "summarize this text: Provider switching test."
        )

        assert result.error is None, f"Process failed: {result.error}"
        assert result.success is True, (
            "Explicit provider should produce a successful result"
        )
        assert result.manifest_created is False, (
            "Should match existing text_summarize manifest"
        )
        manifest_info = result.record.get("manifest", {})
        assert manifest_info.get("name") == "text_summarize", (
            f"Expected text_summarize, got {manifest_info.get('name')!r}"
        )

    @pytest.mark.skipif(
        not PROVIDER_AVAILABLE,
        reason="[skip] no LLM provider available",
    )
    def test_multiple_provider_instances_isolated(
        self,
        registry_with_summarize: CapabilityRegistry,
        executor_with_simulated: Executor,
        provider: Any,
        tmp_path: Path,
    ) -> None:
        """Two separate provider instances can power independent AskSessions
        without interfering with each other."""
        provider_a = ProviderFactory.create("auto")
        provider_b = ProviderFactory.create("auto")

        session_a = _make_session(
            registry_with_summarize,
            executor_with_simulated,
            provider_a,
            tmp_path,
            name="session_a.db",
        )
        session_b = _make_session(
            registry_with_summarize,
            executor_with_simulated,
            provider_b,
            tmp_path,
            name="session_b.db",
        )

        result_a = session_a.process(
            "summarize this: First independent session."
        )
        result_b = session_b.process(
            "summarize this: Second independent session."
        )

        assert result_a.error is None, f"Session A failed: {result_a.error}"
        assert result_b.error is None, f"Session B failed: {result_b.error}"
        assert result_a.success is True, "Session A should succeed"
        assert result_b.success is True, "Session B should succeed"

        # Both should produce readable summaries
        assert len(result_a.summary) > 0, "Session A summary should be non-empty"
        assert len(result_b.summary) > 0, "Session B summary should be non-empty"


# ====================================================================
# Provider detection tests (sanity checks, no LLM call required)
# ====================================================================


@pytest.mark.ask_e2e
class TestProviderDetection:
    """Sanity checks on the provider detection logic itself.

    These tests do NOT make LLM calls — they only verify that the detection
    function returns a consistent result.
    """

    def test_provider_available_flag_is_consistent(self) -> None:
        """The ``PROVIDER_AVAILABLE`` module constant is a boolean."""
        assert isinstance(PROVIDER_AVAILABLE, bool)

    def test_provider_name_type(self) -> None:
        """When a provider IS available, ``_PROVIDER_NAME`` is a string."""
        if PROVIDER_AVAILABLE:
            assert isinstance(_PROVIDER_NAME, str), (
                f"Expected str, got {type(_PROVIDER_NAME).__name__}: {_PROVIDER_NAME!r}"
            )
        else:
            # When unavailable, the name should be None
            assert _PROVIDER_NAME is None
