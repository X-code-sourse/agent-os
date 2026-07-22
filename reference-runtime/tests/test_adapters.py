"""
Intent OS — Runtime Adapter Unit Tests

Tests cover the pure, non-network functions in all 6 adapters:
  1. base.py — AdapterBase abstract interface
  2. openai_adapter.py — schema translation + cost calculation
  3. anthropic_adapter.py — schema translation + cost calculation
  4. ollama_adapter.py — output prompt builder + cost calculation
  5. openrouter_adapter.py — schema translation + cost calculation
  6. github_models_adapter.py — schema translation + cost calculation

The execute() methods make real API calls and are not unit-tested here.
They are verified through integration tests and the Phase 0 cross-runtime
validation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.models import (
    CapabilityManifest,
    CostSpec,
    FieldSchema,
    MetadataSpec,
    RequirementSpec,
    SecuritySpec,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_manifest(
    name: str = "test_capability",
    version: str = "1.0.0",
    description: str = "A test capability",
    input_fields: dict[str, FieldSchema] | None = None,
    output_fields: dict[str, FieldSchema] | None = None,
) -> CapabilityManifest:
    """Create a CapabilityManifest with sensible defaults for testing."""
    if input_fields is None:
        input_fields = {
            "query": FieldSchema(type="string", description="The search query"),
        }
    if output_fields is None:
        output_fields = {
            "summary": FieldSchema(type="string", description="The summary"),
        }
    return CapabilityManifest(
        metadata=MetadataSpec(
            name=name,
            version=version,
            publisher="test",
            description=description,
        ),
        input_schema=input_fields,
        output_schema=output_fields,
        requirements=RequirementSpec(models=["test"]),
        security=SecuritySpec(),
    )


# ====================================================================
# 1. AdapterBase
# ====================================================================

class TestAdapterBase:
    """Test the abstract base adapter interface."""

    def test_can_execute_default_returns_true(self):
        """can_execute() should return True by default."""
        from adapters.base import AdapterBase
        # We can't instantiate ABC directly, so test the default implementation
        # via a concrete adapter's inherited method
        from adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        manifest = _make_manifest()
        assert adapter.can_execute(manifest) is True

    def test_adapter_property_names(self):
        """All adapter properties should return non-empty strings."""
        adapters = self._get_all_adapters()
        for name, adapter in adapters:
            assert adapter.name, f"{name}.name is empty"
            assert adapter.version, f"{name}.version is empty"
            assert adapter.default_model, f"{name}.default_model is empty"

    def _get_all_adapters(self):
        """Import all adapters and return (name, instance) tuples."""
        result = []
        from adapters.openai_adapter import OpenAIAdapter
        result.append(("OpenAIAdapter", OpenAIAdapter()))
        from adapters.anthropic_adapter import AnthropicAdapter
        result.append(("AnthropicAdapter", AnthropicAdapter()))
        from adapters.ollama_adapter import OllamaAdapter
        result.append(("OllamaAdapter", OllamaAdapter()))
        from adapters.openrouter_adapter import OpenRouterAdapter
        result.append(("OpenRouterAdapter", OpenRouterAdapter()))
        from adapters.github_models_adapter import GitHubModelsAdapter
        result.append(("GitHubModelsAdapter", GitHubModelsAdapter()))
        return result

    def test_all_adapters_have_unique_names(self):
        """All adapter names should be unique."""
        adapters = self._get_all_adapters()
        names = [a.name for _, a in adapters]
        assert len(names) == len(set(names)), f"Duplicate adapter names: {names}"


# ====================================================================
# 2. OpenAI Adapter
# ====================================================================

class TestOpenAIAdapter:
    """Test pure functions in the OpenAI adapter."""

    def test_cost_for_known_model(self):
        """Known models should return correct pricing."""
        from adapters.openai_adapter import _calculate_cost
        # gpt-4o: $2.50/M input, $10.00/M output
        cost = _calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
        expected = (1000 / 1_000_000 * 2.50) + (500 / 1_000_000 * 10.00)
        assert cost == expected

    def test_cost_for_unknown_model(self):
        """Unknown models should use default pricing."""
        from adapters.openai_adapter import _calculate_cost
        cost = _calculate_cost("unknown-model", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_cost_zero_tokens(self):
        """Zero tokens should cost zero."""
        from adapters.openai_adapter import _calculate_cost
        assert _calculate_cost("gpt-4o", 0, 0) == 0.0

    def test_schema_to_openai_params_basic_types(self):
        """All basic types should map correctly."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "text": FieldSchema(type="string", description="A text field"),
            "count": FieldSchema(type="integer", description="An integer"),
            "price": FieldSchema(type="number", description="A number"),
            "active": FieldSchema(type="boolean", description="A boolean"),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["type"] == "object"
        assert params["properties"]["text"]["type"] == "string"
        assert params["properties"]["count"]["type"] == "integer"
        assert params["properties"]["price"]["type"] == "number"
        assert params["properties"]["active"]["type"] == "boolean"

    def test_schema_to_openai_params_required_fields(self):
        """Non-optional fields should appear in required list."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "required_field": FieldSchema(type="string"),
            "optional_field": FieldSchema(type="string", optional=True),
        }
        params = _schema_to_openai_params(output_schema)
        assert "required_field" in params["required"]
        assert "optional_field" not in params["required"]

    def test_schema_to_openai_params_enum(self):
        """Enum constraints should be preserved."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "category": FieldSchema(
                type="string", description="Category",
                enum=["tech", "finance", "health"],
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["category"]["enum"] == ["tech", "finance", "health"]

    def test_schema_to_openai_params_min_max(self):
        """Numeric min/max constraints should be preserved."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "age": FieldSchema(type="integer", minimum=0, maximum=150),
            "score": FieldSchema(type="number", minimum=0.0, maximum=100.0),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["age"]["minimum"] == 0
        assert params["properties"]["age"]["maximum"] == 150
        assert params["properties"]["score"]["minimum"] == 0.0
        assert params["properties"]["score"]["maximum"] == 100.0

    def test_schema_to_openai_params_array(self):
        """Array with items should include items schema."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "tags": FieldSchema(
                type="array", description="Tags",
                items=FieldSchema(type="string", description="A tag"),
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["tags"]["type"] == "array"
        assert params["properties"]["tags"]["items"]["type"] == "string"

    def test_schema_to_openai_params_nested_object(self):
        """Nested object with properties should be preserved."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "metadata": FieldSchema(
                type="object", description="Metadata",
                properties={
                    "author": FieldSchema(type="string", description="Author name"),
                    "version": FieldSchema(type="integer", description="Version"),
                },
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["metadata"]["type"] == "object"
        assert params["properties"]["metadata"]["properties"]["author"]["type"] == "string"
        assert params["properties"]["metadata"]["properties"]["version"]["type"] == "integer"

    def test_schema_to_openai_params_descriptions(self):
        """Field descriptions should be preserved."""
        from adapters.openai_adapter import _schema_to_openai_params
        output_schema = {
            "name": FieldSchema(type="string", description="The name of the item"),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["name"]["description"] == "The name of the item"


# ====================================================================
# 3. Anthropic Adapter
# ====================================================================

class TestAnthropicAdapter:
    """Test pure functions in the Anthropic adapter."""

    def test_cost_for_known_model(self):
        """Known models should return correct pricing."""
        from adapters.anthropic_adapter import _calculate_cost
        # claude-sonnet-4: $3.00/M input, $15.00/M output
        cost = _calculate_cost("claude-sonnet-4", input_tokens=1000, output_tokens=500)
        expected = (1000 / 1_000_000 * 3.00) + (500 / 1_000_000 * 15.00)
        assert cost == expected

    def test_cost_for_unknown_model(self):
        """Unknown models should use default pricing."""
        from adapters.anthropic_adapter import _calculate_cost
        assert _calculate_cost("unknown-model", 1000, 500) > 0.0

    def test_cost_zero_tokens(self):
        """Zero tokens should cost zero."""
        from adapters.anthropic_adapter import _calculate_cost
        assert _calculate_cost("claude-sonnet-4", 0, 0) == 0.0

    def test_schema_to_anthropic_tool_basic_types(self):
        """All basic types should map correctly."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        input_schema = {
            "text": FieldSchema(type="string", description="A text field"),
            "count": FieldSchema(type="integer", description="An integer"),
            "price": FieldSchema(type="number", description="A number"),
            "active": FieldSchema(type="boolean", description="A boolean"),
        }
        tool = _schema_to_anthropic_tool(input_schema, "test_tool", "A test tool")
        assert tool["name"] == "test_tool"
        assert tool["description"] == "A test tool"
        props = tool["input_schema"]["properties"]
        assert props["text"]["type"] == "string"
        assert props["count"]["type"] == "integer"
        assert props["price"]["type"] == "number"
        assert props["active"]["type"] == "boolean"

    def test_schema_to_anthropic_tool_required_fields(self):
        """Non-optional fields should appear in required list."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        input_schema = {
            "required_field": FieldSchema(type="string"),
            "optional_field": FieldSchema(type="string", optional=True),
        }
        tool = _schema_to_anthropic_tool(input_schema, "test", "")
        assert "required_field" in tool["input_schema"].get("required", [])
        assert "optional_field" not in tool["input_schema"].get("required", [])

    def test_schema_to_anthropic_tool_enum(self):
        """Enum constraints should be preserved."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        input_schema = {
            "category": FieldSchema(
                type="string",
                enum=["low", "medium", "high"],
            ),
        }
        tool = _schema_to_anthropic_tool(input_schema, "classify", "")
        assert tool["input_schema"]["properties"]["category"]["enum"] == ["low", "medium", "high"]

    def test_schema_to_anthropic_tool_nested_object(self):
        """Nested object with properties should be preserved."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        input_schema = {
            "config": FieldSchema(
                type="object",
                properties={
                    "mode": FieldSchema(type="string", description="Mode"),
                    "depth": FieldSchema(type="integer", description="Depth"),
                },
            ),
        }
        tool = _schema_to_anthropic_tool(input_schema, "analyze", "")
        props = tool["input_schema"]["properties"]
        assert props["config"]["type"] == "object"
        assert props["config"]["properties"]["mode"]["type"] == "string"
        assert props["config"]["properties"]["depth"]["type"] == "integer"

    def test_schema_to_anthropic_tool_name_and_description(self):
        """Tool name and description should be preserved."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        tool = _schema_to_anthropic_tool({}, "my_tool", "My custom tool")
        assert tool["name"] == "my_tool"
        assert tool["description"] == "My custom tool"

    def test_schema_to_anthropic_tool_empty_schema(self):
        """Empty input schema should produce valid tool with empty properties."""
        from adapters.anthropic_adapter import _schema_to_anthropic_tool
        tool = _schema_to_anthropic_tool({}, "empty_tool", "")
        assert tool["input_schema"]["properties"] == {}
        assert tool["input_schema"]["required"] == []


# ====================================================================
# 4. Ollama Adapter
# ====================================================================

class TestOllamaAdapter:
    """Test pure functions in the Ollama adapter."""

    def test_cost_is_always_zero(self):
        """Ollama local inference should always cost $0."""
        from adapters.ollama_adapter import _calculate_cost
        assert _calculate_cost("any-model", 999999, 999999) == 0.0

    def test_build_output_prompt_basic(self):
        """Prompt should include capability name and description."""
        from adapters.ollama_adapter import _build_output_prompt
        manifest = _make_manifest(
            name="text_summarize",
            description="Summarize the input text",
        )
        prompt = _build_output_prompt(manifest, {"text": "Hello world"})
        assert "text_summarize" in prompt
        assert "Summarize the input text" in prompt
        assert '"text": "Hello world"' in prompt
        # Should explicitly instruct JSON-only output
        assert "Return ONLY the JSON object" in prompt

    def test_build_output_prompt_output_schema(self):
        """Output schema fields should appear in the prompt."""
        from adapters.ollama_adapter import _build_output_prompt
        manifest = _make_manifest(
            output_fields={
                "summary": FieldSchema(type="string", description="The generated summary"),
                "key_points": FieldSchema(
                    type="array", description="Key points",
                    items=FieldSchema(type="string"),
                ),
            },
        )
        prompt = _build_output_prompt(manifest, {"text": "test"})
        assert "summary" in prompt
        assert "string" in prompt
        assert "key_points" in prompt
        assert "[string]" in prompt  # array items notation

    def test_build_output_prompt_optional_field(self):
        """Optional fields should be marked in the prompt."""
        from adapters.ollama_adapter import _build_output_prompt
        manifest = _make_manifest(
            output_fields={
                "required": FieldSchema(type="string", description="Required field"),
                "optional": FieldSchema(type="string", description="Optional field", optional=True),
            },
        )
        prompt = _build_output_prompt(manifest, {"text": "test"})
        assert "optional" in prompt
        assert "(optional)" in prompt.lower() or "(optional)" in prompt

    def test_build_output_prompt_no_description(self):
        """Missing description should use fallback text."""
        from adapters.ollama_adapter import _build_output_prompt
        manifest = CapabilityManifest(
            metadata=MetadataSpec(name="no_desc", version="1.0.0"),
            input_schema={"input": FieldSchema(type="string")},
            output_schema={"output": FieldSchema(type="string")},
        )
        prompt = _build_output_prompt(manifest, {"input": "test"})
        assert "No description provided" in prompt


# ====================================================================
# 5. OpenRouter Adapter
# ====================================================================

class TestOpenRouterAdapter:
    """Test pure functions in the OpenRouter adapter."""

    def test_cost_for_known_openai_model(self):
        """OpenAI models via OpenRouter should use correct pricing."""
        from adapters.openrouter_adapter import _calculate_cost
        cost = _calculate_cost("openai/gpt-4o", input_tokens=1000, output_tokens=500)
        expected = (1000 / 1_000_000 * 2.50) + (500 / 1_000_000 * 10.00)
        assert cost == expected

    def test_cost_for_known_anthropic_model(self):
        """Anthropic models via OpenRouter should use correct pricing."""
        from adapters.openrouter_adapter import _calculate_cost
        cost = _calculate_cost(
            "anthropic/claude-sonnet-4",
            input_tokens=2000,
            output_tokens=1000,
        )
        expected = (2000 / 1_000_000 * 3.00) + (1000 / 1_000_000 * 15.00)
        assert cost == expected

    def test_cost_for_unknown_model(self):
        """Unknown models should use default pricing."""
        from adapters.openrouter_adapter import _calculate_cost
        assert _calculate_cost("unknown/model", 1000, 500) > 0.0

    def test_cost_zero_tokens(self):
        """Zero tokens should cost zero."""
        from adapters.openrouter_adapter import _calculate_cost
        assert _calculate_cost("openai/gpt-4o", 0, 0) == 0.0

    def test_schema_to_openai_params(self):
        """Schema to OpenAI params should work for OpenRouter (same format)."""
        from adapters.openrouter_adapter import _schema_to_openai_params
        output_schema = {
            "name": FieldSchema(type="string", description="Name"),
            "count": FieldSchema(type="integer"),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["name"]["type"] == "string"
        assert params["properties"]["count"]["type"] == "integer"
        assert "name" in params.get("required", [])

    def test_schema_to_openai_params_array_with_items(self):
        """Array type with items should include items description."""
        from adapters.openrouter_adapter import _schema_to_openai_params
        output_schema = {
            "results": FieldSchema(
                type="array", description="List of results",
                items=FieldSchema(type="string", description="A result"),
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["results"]["type"] == "array"
        assert params["properties"]["results"]["items"]["type"] == "string"

    def test_schema_to_openai_params_optional_fields(self):
        """Optional fields should not be in required list."""
        from adapters.openrouter_adapter import _schema_to_openai_params
        output_schema = {
            "required_field": FieldSchema(type="string"),
            "optional_field": FieldSchema(type="integer", optional=True),
        }
        params = _schema_to_openai_params(output_schema)
        assert "required_field" in params["required"]
        assert "optional_field" not in params["required"]


# ====================================================================
# 6. GitHub Models Adapter
# ====================================================================

class TestGitHubModelsAdapter:
    """Test pure functions in the GitHub Models adapter."""

    def test_cost_is_always_zero(self):
        """GitHub Models free tier should always cost $0."""
        from adapters.github_models_adapter import _calculate_cost
        assert _calculate_cost("gpt-4o", 999999, 999999) == 0.0

    def test_schema_to_openai_params_basic(self):
        """Basic type mapping should work."""
        from adapters.github_models_adapter import _schema_to_openai_params
        output_schema = {
            "text": FieldSchema(type="string", description="Text"),
            "number": FieldSchema(type="integer"),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["text"]["type"] == "string"
        assert params["properties"]["number"]["type"] == "integer"

    def test_schema_to_openai_params_enum_and_constraints(self):
        """Enum and numeric constraints should be preserved."""
        from adapters.github_models_adapter import _schema_to_openai_params
        output_schema = {
            "color": FieldSchema(
                type="string", enum=["red", "green", "blue"],
            ),
            "quantity": FieldSchema(
                type="integer", minimum=0, maximum=100,
            ),
            "price": FieldSchema(
                type="number", minimum=0.0, maximum=9999.99,
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["color"]["enum"] == ["red", "green", "blue"]
        assert params["properties"]["quantity"]["minimum"] == 0
        assert params["properties"]["quantity"]["maximum"] == 100
        assert params["properties"]["price"]["minimum"] == 0.0
        assert params["properties"]["price"]["maximum"] == 9999.99

    def test_schema_to_openai_params_array_items(self):
        """Array with items should preserve items type."""
        from adapters.github_models_adapter import _schema_to_openai_params
        output_schema = {
            "tags": FieldSchema(
                type="array",
                items=FieldSchema(type="string"),
            ),
        }
        params = _schema_to_openai_params(output_schema)
        assert params["properties"]["tags"]["items"]["type"] == "string"

    def test_schema_to_openai_params_optional(self):
        """Optional fields should not be required."""
        from adapters.github_models_adapter import _schema_to_openai_params
        output_schema = {
            "req": FieldSchema(type="string"),
            "opt": FieldSchema(type="string", optional=True),
        }
        params = _schema_to_openai_params(output_schema)
        assert "req" in params["required"]
        assert "opt" not in params["required"]


# ====================================================================
# 7. Cross-Adapter Consistency
# ====================================================================

class TestCrossAdapterConsistency:
    """Tests that verify consistent behavior across all adapters.

    These tests ensure that the adapter layer maintains consistent
    translation behavior — the same Intent OS schema should produce
    compatible runtime-specific formats.
    """

    def test_cost_function_signature(self):
        """All adapters should have consistent _calculate_cost signatures."""
        from adapters.openai_adapter import _calculate_cost as oa
        from adapters.anthropic_adapter import _calculate_cost as aa
        from adapters.ollama_adapter import _calculate_cost as ol
        from adapters.openrouter_adapter import _calculate_cost as or_
        from adapters.github_models_adapter import _calculate_cost as gm

        for fn in [oa, aa, ol, or_, gm]:
            # All accept (model, input_tokens, output_tokens) and return float
            result = fn("test-model", 100, 50)
            assert isinstance(result, float), f"{fn.__module__} returned {type(result)}"

    def test_all_adapters_expose_required_properties(self):
        """Every adapter class should expose name, version, default_model."""
        adapters = []
        from adapters.openai_adapter import OpenAIAdapter
        adapters.append(OpenAIAdapter)
        from adapters.anthropic_adapter import AnthropicAdapter
        adapters.append(AnthropicAdapter)
        from adapters.ollama_adapter import OllamaAdapter
        adapters.append(OllamaAdapter)
        from adapters.openrouter_adapter import OpenRouterAdapter
        adapters.append(OpenRouterAdapter)
        from adapters.github_models_adapter import GitHubModelsAdapter
        adapters.append(GitHubModelsAdapter)

        for cls in adapters:
            instance = cls()
            assert hasattr(instance, 'name')
            assert hasattr(instance, 'version')
            assert hasattr(instance, 'default_model')
            assert hasattr(instance, 'execute')
            assert hasattr(instance, 'can_execute')

    def test_all_adapters_adhere_to_base(self):
        """Every adapter should be a subclass of AdapterBase."""
        from adapters.base import AdapterBase

        from adapters.openai_adapter import OpenAIAdapter
        from adapters.anthropic_adapter import AnthropicAdapter
        from adapters.ollama_adapter import OllamaAdapter
        from adapters.openrouter_adapter import OpenRouterAdapter
        from adapters.github_models_adapter import GitHubModelsAdapter

        for cls in [OpenAIAdapter, AnthropicAdapter, OllamaAdapter,
                     OpenRouterAdapter, GitHubModelsAdapter]:
            assert issubclass(cls, AdapterBase), f"{cls.__name__} does not inherit AdapterBase"

    def test_adapter_versions_match(self):
        """All adapters should use the same version for Phase 0."""
        from adapters.openai_adapter import OpenAIAdapter
        from adapters.anthropic_adapter import AnthropicAdapter
        from adapters.ollama_adapter import OllamaAdapter
        from adapters.openrouter_adapter import OpenRouterAdapter
        from adapters.github_models_adapter import GitHubModelsAdapter

        for cls in [OpenAIAdapter, AnthropicAdapter, OllamaAdapter,
                     OpenRouterAdapter, GitHubModelsAdapter]:
            instance = cls()
            assert instance.version == "0.1.0", (
                f"{cls.__name__} version is '{instance.version}', expected '0.1.0'"
            )

    def test_openai_and_github_produce_consistent_params(self):
        """OpenAI and GitHub Models adapters should produce the same schema params
        for the same output schema, since GitHub Models uses OpenAI-compatible API."""
        from adapters.openai_adapter import _schema_to_openai_params as openai_fn
        from adapters.github_models_adapter import _schema_to_openai_params as github_fn

        output_schema = {
            "title": FieldSchema(type="string", description="Title"),
            "score": FieldSchema(type="number", minimum=0.0, maximum=1.0),
            "tags": FieldSchema(
                type="array",
                items=FieldSchema(type="string"),
                optional=True,
            ),
        }

        openai_result = openai_fn(output_schema)
        github_result = github_fn(output_schema)
        assert openai_result == github_result, (
            "OpenAI and GitHub Models adapters produce different schema params"
        )

    def test_openai_and_openrouter_cost_scope(self):
        """OpenAI and OpenRouter cost functions should not overlap pricing tables.
        OpenRouter uses namespaced model names (openai/gpt-4o), while OpenAI
        uses bare names. They should not share pricing entries."""
        from adapters.openai_adapter import PRICING as openai_pricing
        from adapters.openrouter_adapter import PRICING as openrouter_pricing

        # No model name should appear in both tables (since OpenRouter
        # uses namespaced names like 'openai/gpt-4o')
        for model in openai_pricing:
            assert model not in openrouter_pricing, (
                f"Model '{model}' appears in both OpenAI and OpenRouter pricing"
            )
