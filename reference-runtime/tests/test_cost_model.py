"""
Intent OS — Cost Model & Planner Tests

Tests cover:
  1. CostEstimate dataclass construction and normalization
  2. CostModel._default_estimate() for ollama (should be $0)
  3. CostModel._default_estimate() for openai (should be > $0)
  4. CostModel.estimate() with no event store (falls back to defaults)
  5. CostModel.estimate() with mock analytics data (uses historical)
  6. CostModel.estimate() confidence='high' when enough records
  7. CostModel.estimate() confidence='low' with no data
  8. MultiPlanResult dataclass construction
  9. Planner.plan_candidates() returns sorted list
  10. Backward compat: Planner.plan() still works unchanged
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is in path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from core.cost_model import (
    CostModel,
    CostEstimate,
    MultiPlanResult,
    ADAPTER_BASE_LATENCY_MS,
)
from core.planner import WorkflowPlanner, PlanResult
from core.models import (
    CapabilityManifest,
    MetadataSpec,
    FieldSchema,
    RequirementSpec,
    SecuritySpec,
    CostSpec,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_manifest(
    name: str = "test_cap",
    version: str = "1.0.0",
    pricing_hint: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        metadata=MetadataSpec(name=name, version=version, publisher="test"),
        input_schema={"text": FieldSchema(type="string")},
        output_schema={"summary": FieldSchema(type="string")},
        requirements=RequirementSpec(),
        security=SecuritySpec(),
        cost=CostSpec(pricing_hint=pricing_hint) if pricing_hint else None,
    )


# ====================================================================
# 1. CostEstimate Dataclass Construction
# ====================================================================

class TestCostEstimateConstruction:
    """Tests for CostEstimate dataclass construction and __post_init__ normalization."""

    def test_basic_construction(self):
        """All fields should be set from constructor args."""
        est = CostEstimate(
            cost_usd=0.05, latency_ms=1500, tokens=500,
            confidence="high", source="default",
        )
        assert est.cost_usd == 0.05
        assert est.latency_ms == 1500
        assert est.tokens == 500
        assert est.confidence == "high"
        assert est.source == "default"

    def test_negative_cost_clamped_to_zero(self):
        """Negative cost should be clamped to 0.0."""
        est = CostEstimate(-1.0, 100, 50, "low", "default")
        assert est.cost_usd == 0.0

    def test_negative_latency_clamped_to_zero(self):
        """Negative latency should be clamped to 0."""
        est = CostEstimate(0.1, -500, 50, "low", "default")
        assert est.latency_ms == 0

    def test_negative_tokens_clamped_to_zero(self):
        """Negative tokens should be clamped to 0."""
        est = CostEstimate(0.1, 100, -10, "low", "default")
        assert est.tokens == 0

    def test_float_latency_truncated_to_int(self):
        """Float latency should be truncated (not rounded) to int."""
        est = CostEstimate(0.1, 123.7, 50, "low", "default")
        assert est.latency_ms == 123

    def test_invalid_confidence_falls_back_to_low(self):
        """Invalid confidence value should default to 'low'."""
        est = CostEstimate(0.1, 100, 50, "super_high", "default")
        assert est.confidence == "low"

    def test_invalid_source_falls_back_to_default(self):
        """Invalid source value should default to 'default'."""
        est = CostEstimate(0.1, 100, 50, "low", "unknown_source")
        assert est.source == "default"

    def test_cost_rounded_to_six_decimals(self):
        """Cost should be rounded to 6 decimal places."""
        est = CostEstimate(0.123456789, 100, 50, "low", "default")
        assert est.cost_usd == 0.123457


# ====================================================================
# 2-3. CostModel._default_estimate() — Pricing
# ====================================================================

class TestDefaultEstimate:
    """Tests for CostModel._default_estimate() pricing and latency."""

    def test_ollama_is_free(self):
        """_default_estimate for ollama should return $0 cost (local inference)."""
        model = CostModel()
        manifest = _make_manifest()
        est = model._default_estimate(manifest, "ollama", input_size_chars=1000)
        assert est.cost_usd == 0.0
        assert est.source == "default"
        assert est.confidence == "low"

    def test_openai_estimate_positive_cost(self):
        """_default_estimate for openai should return > $0 cost."""
        model = CostModel()
        manifest = _make_manifest()
        est = model._default_estimate(manifest, "openai", input_size_chars=1000)
        assert est.cost_usd > 0.0
        assert est.source == "default"

    def test_openai_estimate_scales_with_input_size(self):
        """Larger input should produce higher cost and token count."""
        model = CostModel()
        manifest = _make_manifest()
        small = model._default_estimate(manifest, "openai", input_size_chars=100)
        large = model._default_estimate(manifest, "openai", input_size_chars=10000)
        assert small.cost_usd < large.cost_usd
        assert small.tokens < large.tokens

    def test_openai_latency_includes_base_and_token_overhead(self):
        """Latency should be at least the adapter's base latency."""
        model = CostModel()
        manifest = _make_manifest()
        est = model._default_estimate(manifest, "openai", input_size_chars=1000)
        base = ADAPTER_BASE_LATENCY_MS["openai"]
        assert est.latency_ms >= base

    def test_unknown_adapter_falls_back_to_defaults(self):
        """Unknown adapter should use fallback latency and gpt-4o pricing."""
        model = CostModel()
        manifest = _make_manifest()
        est = model._default_estimate(manifest, "unknown_runtime", input_size_chars=1000)
        # Fallback latency is 2000ms
        assert est.latency_ms >= 2000
        assert est.cost_usd > 0.0

    def test_github_models_is_free(self):
        """github-models adapter should have zero cost (free tier)."""
        model = CostModel()
        manifest = _make_manifest()
        est = model._default_estimate(manifest, "github-models", input_size_chars=1000)
        assert est.cost_usd == 0.0

    def test_manifest_pricing_hint_affects_cost(self):
        """Manifest with pricing_hint for a cheaper model should lower cost."""
        model = CostModel()
        # claude-haiku-3.5 is cheaper than default claude-sonnet-4 for anthropic
        manifest_with_hint = _make_manifest(pricing_hint="claude-haiku-3.5")
        manifest_default = _make_manifest()
        est_cheap = model._default_estimate(manifest_with_hint, "anthropic", input_size_chars=10000)
        est_default = model._default_estimate(manifest_default, "anthropic", input_size_chars=10000)
        assert est_cheap.cost_usd < est_default.cost_usd


# ====================================================================
# 4. CostModel.estimate() — No Analytics (Fallback to Defaults)
# ====================================================================

class TestEstimateNoAnalytics:
    """CostModel.estimate() falls back to default pricing when no analytics."""

    def test_no_analytics_falls_back_to_default(self):
        """Without analytics, estimate should return source='default'."""
        model = CostModel()
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "default"
        assert est.confidence == "low"
        assert est.cost_usd > 0.0

    def test_no_analytics_ollama_is_free(self):
        """Without analytics, ollama should still be estimated at $0."""
        model = CostModel()
        manifest = _make_manifest()
        est = model.estimate(manifest, "ollama", input_size_chars=1000)
        assert est.cost_usd == 0.0
        assert est.source == "default"

    def test_no_analytics_passes_event_store(self):
        """CostModel can be constructed with event_store but no analytics."""
        store = MagicMock()
        model = CostModel(event_store=store, analytics=None)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "default"


# ====================================================================
# 5-7. CostModel.estimate() — With Mock Analytics
# ====================================================================

class TestEstimateWithAnalytics:
    """CostModel.estimate() should use historical data when analytics is available."""

    @pytest.fixture
    def mock_analytics(self):
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = [
            {
                "capability": "test_cap",
                "total_runs": 15,
                "avg_cost_usd": 0.025,
                "avg_latency_ms": 1200.0,
                "avg_tokens": 600,
                "success_rate": 0.95,
            },
        ]
        analytics.get_runtime_comparison.return_value = [
            {
                "runtime_id": "openai",
                "total_runs": 30,
                "avg_cost_usd": 0.030,
                "avg_latency_ms": 1400.0,
                "avg_tokens": 650,
                "success_rate": 0.93,
            },
        ]
        return analytics

    def test_uses_historical_data(self, mock_analytics):
        """With analytics, estimate should return source='historical'."""
        model = CostModel(analytics=mock_analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "historical"

    def test_historical_confidence_high_with_enough_records(self, mock_analytics):
        """With >= 10 total historical records, confidence should be 'high'."""
        model = CostModel(analytics=mock_analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        # cap_count=15 + runtime_count=30 = 45 (>= 10)
        assert est.confidence == "high"

    def test_historical_confidence_low_with_no_data(self):
        """When analytics returns empty data, falls back to default with 'low' confidence."""
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = []
        analytics.get_runtime_comparison.return_value = []
        model = CostModel(analytics=analytics)
        manifest = _make_manifest("nonexistent_cap")
        est = model.estimate(manifest, "unknown_runtime", input_size_chars=1000)
        # No matching entries → _historical_estimate returns None → fallback to default
        assert est.source == "default"
        assert est.confidence == "low"

    def test_historical_medium_confidence(self):
        """With 3-9 total records, confidence should be 'medium'."""
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = [
            {
                "capability": "test_cap",
                "total_runs": 5,
                "avg_cost_usd": 0.02,
                "avg_latency_ms": 1000.0,
                "avg_tokens": 500,
            },
        ]
        analytics.get_runtime_comparison.return_value = []
        model = CostModel(analytics=analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "historical"
        assert est.confidence == "medium"

    def test_history_weighted_average(self, mock_analytics):
        """With both cap and runtime stats, cost should be a weighted average."""
        model = CostModel(analytics=mock_analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        # cap_count=15, runtime_count=30, total=45
        # cap_weight=15/45=1/3, runtime_weight=30/45=2/3
        # cost = 0.025*(1/3) + 0.030*(2/3) = 0.02833...
        # Verify the result sits between the two component costs
        assert 0.025 < est.cost_usd < 0.030

    def test_analytics_exception_falls_back_to_default(self):
        """When analytics raises an exception, estimate should fall back to default."""
        analytics = MagicMock()
        analytics.get_capability_rankings.side_effect = RuntimeError("DB error")
        analytics.get_runtime_comparison.side_effect = RuntimeError("DB error")
        model = CostModel(analytics=analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "default"
        assert est.confidence == "low"

    def test_history_capability_only(self):
        """When only capability-level stats exist, use them directly."""
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = [
            {
                "capability": "test_cap",
                "total_runs": 12,
                "avg_cost_usd": 0.015,
                "avg_latency_ms": 800.0,
                "avg_tokens": 400,
            },
        ]
        analytics.get_runtime_comparison.return_value = []
        model = CostModel(analytics=analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "historical"
        assert est.cost_usd == 0.015

    def test_history_runtime_only(self):
        """When only runtime-level stats exist, use them directly."""
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = []
        analytics.get_runtime_comparison.return_value = [
            {
                "runtime_id": "openai",
                "total_runs": 20,
                "avg_cost_usd": 0.040,
                "avg_latency_ms": 1500.0,
                "avg_tokens": 700,
            },
        ]
        model = CostModel(analytics=analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "historical"
        assert est.cost_usd == 0.040

    def test_history_zero_total_runs_returns_none(self):
        """When total_records is 0, _historical_estimate should return None (fallback)."""
        analytics = MagicMock()
        analytics.get_capability_rankings.return_value = [
            {
                "capability": "test_cap",
                "total_runs": 0,
                "avg_cost_usd": 0.0,
                "avg_latency_ms": 0.0,
                "avg_tokens": 0,
            },
        ]
        analytics.get_runtime_comparison.return_value = []
        model = CostModel(analytics=analytics)
        manifest = _make_manifest()
        est = model.estimate(manifest, "openai", input_size_chars=1000)
        assert est.source == "default"


# ====================================================================
# 8. MultiPlanResult Dataclass
# ====================================================================

class TestMultiPlanResult:
    """Tests for MultiPlanResult dataclass construction and index normalization."""

    def test_basic_construction(self):
        """Plans and recommended_index should be stored as-is when valid."""
        plans = [("plan_a", CostEstimate(0.1, 100, 50, "low", "default"))]
        result = MultiPlanResult(plans=plans, recommended_index=0)
        assert result.plans == plans
        assert result.recommended_index == 0

    def test_empty_plans_resets_index_to_zero(self):
        """Empty plans list should force recommended_index to 0."""
        result = MultiPlanResult(plans=[], recommended_index=5)
        assert result.plans == []
        assert result.recommended_index == 0

    def test_negative_index_resets_to_zero(self):
        """Negative recommended_index should be reset to 0."""
        plans = [("a", CostEstimate(0.1, 100, 50, "low", "default"))]
        result = MultiPlanResult(plans=plans, recommended_index=-1)
        assert result.recommended_index == 0

    def test_out_of_range_index_resets_to_zero(self):
        """recommended_index >= len(plans) should be reset to 0."""
        plans = [("a", CostEstimate(0.1, 100, 50, "low", "default"))]
        result = MultiPlanResult(plans=plans, recommended_index=10)
        assert result.recommended_index == 0

    def test_multiple_plans_all_stored(self):
        """Multiple plans should all be preserved."""
        plans = [
            ("plan_a", CostEstimate(0.1, 100, 50, "low", "default")),
            ("plan_b", CostEstimate(0.2, 200, 100, "medium", "historical")),
            ("plan_c", CostEstimate(0.3, 300, 150, "high", "historical")),
        ]
        result = MultiPlanResult(plans=plans, recommended_index=1)
        assert len(result.plans) == 3
        assert result.recommended_index == 1


# ====================================================================
# 9. Planner.plan_candidates() — Sorted List
# ====================================================================

class TestPlanCandidates:
    """Tests for WorkflowPlanner.plan_candidates() — returns sorted MultiPlanResult."""

    @pytest.fixture
    def mock_registry(self):
        reg = MagicMock()
        # Multiple matching capabilities per pattern to enable plan variation
        reg.list_capabilities.return_value = [
            {"name": "web_search", "version": "1.0.0"},
            {"name": "premium_search", "version": "1.0.0"},
            {"name": "data_analyze", "version": "1.0.0"},
            {"name": "basic_analyze", "version": "1.0.0"},
            {"name": "report_generator", "version": "1.0.0"},
        ]

        def _get(name: str, version: str) -> CapabilityManifest:
            return CapabilityManifest(
                metadata=MetadataSpec(name=name, version=version, publisher="test"),
                input_schema={"input": FieldSchema(type="string")},
                output_schema={"output": FieldSchema(type="string")},
                requirements=RequirementSpec(),
                security=SecuritySpec(),
            )

        reg.get.side_effect = _get
        return reg

    @pytest.fixture
    def mock_cost_model(self):
        cm = MagicMock(spec=CostModel)

        def _estimate(manifest, adapter_name, input_size_chars=1000):
            costs = {
                "web_search": CostEstimate(0.02, 100, 50, "low", "default"),
                "premium_search": CostEstimate(0.01, 50, 30, "low", "default"),
                "data_analyze": CostEstimate(0.03, 200, 100, "low", "default"),
                "basic_analyze": CostEstimate(0.02, 150, 80, "low", "default"),
                "report_generator": CostEstimate(0.04, 300, 200, "low", "default"),
            }
            return costs.get(manifest.name, CostEstimate(0.01, 100, 50, "low", "default"))

        cm.estimate.side_effect = _estimate
        return cm

    def test_returns_multi_plan_result(self, mock_registry, mock_cost_model):
        """plan_candidates should return a MultiPlanResult."""
        planner = WorkflowPlanner(registry=mock_registry, cost_model=mock_cost_model)
        result = planner.plan_candidates("research AI", top_n=2)
        assert isinstance(result, MultiPlanResult)
        assert len(result.plans) >= 1

    def test_plans_sorted_by_cost_ascending(self, mock_registry, mock_cost_model):
        """Result plans should be sorted cheapest-first."""
        planner = WorkflowPlanner(registry=mock_registry, cost_model=mock_cost_model)
        result = planner.plan_candidates("research AI", top_n=2)
        for i in range(len(result.plans) - 1):
            c1 = result.plans[i][1].cost_usd
            c2 = result.plans[i + 1][1].cost_usd
            assert c1 <= c2, f"Plan {i} cost {c1} > Plan {i+1} cost {c2}"

    def test_recommended_index_is_zero(self, mock_registry, mock_cost_model):
        """recommended_index should point to the cheapest (first) plan."""
        planner = WorkflowPlanner(registry=mock_registry, cost_model=mock_cost_model)
        result = planner.plan_candidates("research AI", top_n=2)
        assert result.recommended_index == 0

    def test_plan_candidates_without_cost_model(self, mock_registry):
        """plan_candidates without CostModel should still return valid MultiPlanResult."""
        planner = WorkflowPlanner(registry=mock_registry)
        result = planner.plan_candidates("research AI", top_n=1)
        assert isinstance(result, MultiPlanResult)
        assert len(result.plans) >= 1
        # Without cost model, _estimate_plan returns a 0-cost default estimate
        assert result.plans[0][1].cost_usd == 0.0
        assert result.plans[0][1].source == "default"

    def test_plan_candidates_handles_goal_without_template_match(self, mock_registry, mock_cost_model):
        """Unmatched goal should still produce candidates via passthrough template."""
        planner = WorkflowPlanner(registry=mock_registry, cost_model=mock_cost_model)
        result = planner.plan_candidates("xyzzy flurbo garblex", top_n=1)
        assert isinstance(result, MultiPlanResult)
        assert len(result.plans) >= 1


# ====================================================================
# 10. Planner.plan() — Backward Compatibility
# ====================================================================

class TestPlanBackwardCompat:
    """Backward compat: Planner.plan() still works with the same signature."""

    @pytest.fixture
    def mock_registry(self):
        reg = MagicMock()
        reg.list_capabilities.return_value = [
            {"name": "web_search", "version": "1.0.0"},
            {"name": "data_analyze", "version": "1.0.0"},
            {"name": "report_generator", "version": "1.0.0"},
        ]

        def _get(name, version):
            return CapabilityManifest(
                metadata=MetadataSpec(name=name, version=version, publisher="test"),
                input_schema={"input": FieldSchema(type="string")},
                output_schema={"output": FieldSchema(type="string")},
                requirements=RequirementSpec(),
                security=SecuritySpec(),
            )

        reg.get.side_effect = _get
        return reg

    def test_plan_returns_plan_result(self):
        """plan() should return a PlanResult (same signature, no new required params)."""
        planner = WorkflowPlanner()
        result = planner.plan("do something")
        assert isinstance(result, PlanResult)

    def test_plan_has_expected_fields(self):
        """PlanResult should contain all the expected fields."""
        planner = WorkflowPlanner()
        result = planner.plan("research AI")
        assert hasattr(result, "workflow_dag")
        assert hasattr(result, "template_name")
        assert hasattr(result, "goal")
        assert hasattr(result, "matched_capabilities")
        assert hasattr(result, "warnings")

    def test_plan_goal_preserved(self):
        """Goal string should be preserved verbatim in the PlanResult."""
        planner = WorkflowPlanner()
        goal = "research the history of computing"
        result = planner.plan(goal)
        assert result.goal == goal

    def test_plan_resolves_capabilities(self, mock_registry):
        """plan() with matching registry should populate matched_capabilities."""
        planner = WorkflowPlanner(registry=mock_registry)
        result = planner.plan("research AI")
        assert len(result.matched_capabilities) > 0

    def test_plan_template_matches_goal(self):
        """Goal matching a template pattern should use that template."""
        planner = WorkflowPlanner()
        result = planner.plan("research something interesting")
        # The research template has name "research"
        assert result.template_name is not None

    def test_plan_passthrough_for_unmatched_goal(self):
        """Unmatched goal should produce a valid PlanResult via passthrough template."""
        planner = WorkflowPlanner()
        result = planner.plan("some completely unrecognizable goal that wont match anything")
        assert isinstance(result, PlanResult)
        assert result.workflow_dag is not None

    def test_plan_with_context(self):
        """plan() should accept optional context dict."""
        planner = WorkflowPlanner()
        result = planner.plan("research AI", context={"topic": "AI safety"})
        assert isinstance(result, PlanResult)

    def test_plan_with_custom_templates(self):
        """Planner with custom templates should still plan."""
        from core.planner import WorkflowTemplate, TemplateTask
        custom = WorkflowTemplate(
            name="custom",
            description="Custom template",
            goal_pattern=r"(?i)custom",
            tasks=[TemplateTask(id="task1", capability_pattern="*")],
            edges=[],
        )
        planner = WorkflowPlanner(templates=[custom])
        result = planner.plan("custom request")
        assert isinstance(result, PlanResult)
        assert result.template_name == "custom"
