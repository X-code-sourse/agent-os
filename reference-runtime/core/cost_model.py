"""
Intent OS — Cost Model (Planner Cost Estimation)

Provides cost, latency, and token estimation for capability execution across
different runtimes/adapters. Used by the Planner to compare candidate plans
and select the optimal execution path.

Phase 1: Cost Model with historical fallback to default pricing.
Phase 3+: Will evolve into the Probabilistic Query Optimizer's cost
          estimation backbone (Algorithm 4 / SPEC-0003).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from core.models import CapabilityManifest

# ---------------------------------------------------------------------------
# Import PlanResult lazily to avoid circular imports
# ---------------------------------------------------------------------------
_PLAN_RESULT_TYPE: Any = None


def _get_plan_result_type():
    """Lazy import of PlanResult to break circular dependency."""
    global _PLAN_RESULT_TYPE
    if _PLAN_RESULT_TYPE is None:
        from core.planner import PlanResult
        _PLAN_RESULT_TYPE = PlanResult
    return _PLAN_RESULT_TYPE


# ---------------------------------------------------------------------------
# Default pricing tables  (embedded — no adapter imports needed)
# ---------------------------------------------------------------------------

# Default models per adapter
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4",
    "ollama": "llama3.2:1b",
    "openrouter": "gpt-4o",
    "github-models": "gpt-4o-mini",
}

# Model pricing per 1M tokens (input/output)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Anthropic
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    # Ollama — local, free
    # OpenRouter — uses openai/anthropic pricing per model
    # GitHub Models — free tier
}

# Models whose cost is always zero (local / free tier)
ZERO_COST_MODELS: set[str] = set()

# Adapter-level pricing overrides: adapter -> model -> pricing
ADAPTER_PRICING: dict[str, dict[str, dict[str, float]]] = {
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    },
    "anthropic": {
        "claude-sonnet-4": {"input": 3.00, "output": 15.00},
        "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    },
    "ollama": {},  # All models free (local inference)
    "openrouter": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "claude-sonnet-4": {"input": 3.00, "output": 15.00},
        "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    },
    "github-models": {},  # Free tier
}

# Base latency (ms) per adapter — represents model response start overhead
ADAPTER_BASE_LATENCY_MS: dict[str, int] = {
    "openai": 1500,
    "anthropic": 2000,
    "ollama": 3000,
    "openrouter": 2000,
    "github-models": 2500,
}

# Fallback latency when adapter is unknown
FALLBACK_LATENCY_MS = 2000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CostEstimate:
    """Estimated cost, latency, and token usage for a planned execution."""

    cost_usd: float
    latency_ms: int
    tokens: int
    confidence: str  # 'low' | 'medium' | 'high'
    source: str  # 'default' | 'historical'

    def __post_init__(self) -> None:
        """Normalize and validate fields."""
        self.cost_usd = round(max(self.cost_usd, 0.0), 6)
        self.latency_ms = max(int(self.latency_ms), 0)
        self.tokens = max(int(self.tokens), 0)
        if self.confidence not in ("low", "medium", "high"):
            self.confidence = "low"
        if self.source not in ("default", "historical"):
            self.source = "default"


@dataclass
class MultiPlanResult:
    """A set of candidate plans each with a cost estimate, plus a recommendation."""

    plans: list[tuple[Any, CostEstimate]]
    recommended_index: int = 0

    def __post_init__(self) -> None:
        if not self.plans:
            self.recommended_index = 0
        elif self.recommended_index < 0 or self.recommended_index >= len(self.plans):
            self.recommended_index = 0


# ---------------------------------------------------------------------------
# Cost Model
# ---------------------------------------------------------------------------

class CostModel:
    """
    Estimates execution cost, latency, and token usage.

    Uses historical data when available (via AnalyticsEngine), falling back
    to embedded default pricing tables otherwise.

    Usage:
        cost_model = CostModel(analytics=analytics_engine)
        estimate = cost_model.estimate(manifest, "openai", input_size_chars=2000)

        # Compare multiple plans
        multi = cost_model.compare_plans([plan_a, plan_b])
        best = multi.plans[multi.recommended_index]
    """

    def __init__(
        self,
        event_store: Any = None,
        analytics: Any = None,
    ) -> None:
        """
        Initialize the cost model.

        Args:
            event_store: Optional EventStore for raw data access.
            analytics: Optional AnalyticsEngine for historical cost data.
        """
        self._event_store = event_store
        self._analytics = analytics

    # ── Public API ──

    def estimate(
        self,
        manifest: CapabilityManifest,
        adapter_name: str,
        input_size_chars: int = 1000,
    ) -> CostEstimate:
        """
        Produce a CostEstimate for executing a capability on a given adapter.

        Strategy:
          1. Try historical estimate first (if analytics is available).
          2. Fall back to default pricing tables.

        Args:
            manifest: The capability manifest to estimate for.
            adapter_name: Adapter/runtime identifier (e.g. "openai", "ollama").
            input_size_chars: Expected input size in characters.

        Returns:
            A CostEstimate with cost, latency, tokens, confidence, and source.
        """
        historical = self._historical_estimate(manifest, adapter_name)
        if historical is not None:
            return historical
        return self._default_estimate(manifest, adapter_name, input_size_chars)

    def compare_plans(
        self,
        plans: list[Any],
        adapter_names: list[str] | None = None,
        input_size_chars: int = 1000,
    ) -> MultiPlanResult:
        """
        Estimate cost for each plan and return a ranked MultiPlanResult.

        Args:
            plans: List of PlanResult objects to compare.
            adapter_names: Optional per-plan adapter overrides. If None,
                           derives from each plan's matched capabilities.
            input_size_chars: Expected input size for estimation.

        Returns:
            MultiPlanResult with estimates sorted cheapest-first, and the
            recommended_index pointing to the cheapest plan.
        """
        PlanResult = _get_plan_result_type()
        plan_estimates: list[tuple[Any, CostEstimate]] = []

        for i, plan in enumerate(plans):
            adapter = (
                adapter_names[i]
                if adapter_names and i < len(adapter_names)
                else self._derive_adapter(plan)
            )

            # Aggregate estimate across all tasks in the plan
            total_cost = 0.0
            total_latency = 0
            total_tokens = 0
            confidences: list[str] = []
            sources: list[str] = []
            task_count = 0

            for task in plan.workflow_dag.tasks:
                cap = plan.matched_capabilities.get(task.id)
                if cap is None:
                    continue
                est = self.estimate(cap, adapter, input_size_chars)
                total_cost += est.cost_usd
                total_latency += est.latency_ms
                total_tokens += est.tokens
                confidences.append(est.confidence)
                sources.append(est.source)
                task_count += 1

            if task_count == 0:
                plan_estimates.append((plan, CostEstimate(0.0, 0, 0, "low", "default")))
                continue

            agg_confidence = self._aggregate_confidence(confidences)
            agg_source = "historical" if any(s == "historical" for s in sources) else "default"

            plan_estimates.append((
                plan,
                CostEstimate(total_cost, total_latency, total_tokens, agg_confidence, agg_source),
            ))

        # Sort by cost ascending (cheapest first)
        plan_estimates.sort(key=lambda x: (x[1].cost_usd, x[1].latency_ms))

        # Recommended index is the cheapest plan
        recommended = 0
        for i, (plan, _) in enumerate(plan_estimates):
            if plan is plans[0]:
                recommended = i
                break

        return MultiPlanResult(plans=plan_estimates, recommended_index=recommended)

    # ── Historical Estimation ──

    def _historical_estimate(
        self,
        manifest: CapabilityManifest,
        adapter_name: str,
    ) -> CostEstimate | None:
        """
        Attempt to estimate from historical analytics data.

        Queries:
          - Capability rankings for per-capability averages.
          - Runtime comparison for per-adapter averages.

        If both capability and runtime records exist, computes a weighted
        average using execution counts.

        Returns:
            CostEstimate if sufficient historical data exists, else None.
        """
        if self._analytics is None:
            return None

        cap_name = manifest.name

        # Gather capability-level stats
        cap_stats = None
        try:
            rankings = self._analytics.get_capability_rankings() or []
            for entry in rankings:
                if entry.get("capability") == cap_name:
                    cap_stats = entry
                    break
        except Exception:
            pass

        # Gather runtime-level stats for this adapter
        runtime_stats = None
        try:
            comparisons = self._analytics.get_runtime_comparison() or []
            for entry in comparisons:
                if entry.get("runtime_id") == adapter_name:
                    runtime_stats = entry
                    break
        except Exception:
            pass

        # Need at least one source of data
        if cap_stats is None and runtime_stats is None:
            return None

        # Determine confidence based on data volume
        cap_count = (cap_stats or {}).get("total_runs", 0) or 0
        runtime_count = (runtime_stats or {}).get("total_runs", 0) or 0
        total_records = cap_count + runtime_count

        if total_records == 0:
            return None

        if total_records >= 10:
            confidence = "high"
        elif total_records >= 3:
            confidence = "medium"
        else:
            confidence = "low"

        # Weighted combination
        if cap_stats and runtime_stats:
            total_weight = max(cap_count + runtime_count, 1)
            cap_weight = cap_count / total_weight
            runtime_weight = runtime_count / total_weight

            cost = (
                (cap_stats.get("avg_cost_usd", 0) or 0) * cap_weight
                + (runtime_stats.get("avg_cost_usd", 0) or 0) * runtime_weight
            )
            latency = (
                (cap_stats.get("avg_latency_ms", 0) or 0) * cap_weight
                + (runtime_stats.get("avg_latency_ms", 0) or 0) * runtime_weight
            )
            tokens = (
                (cap_stats.get("avg_tokens", 0) or 0) * cap_weight
                + (runtime_stats.get("avg_tokens", 0) or 0) * runtime_weight
            )
        elif cap_stats:
            cost = cap_stats.get("avg_cost_usd", 0) or 0
            latency = cap_stats.get("avg_latency_ms", 0) or 0
            tokens = cap_stats.get("avg_tokens", 0) or 0
        else:
            cost = runtime_stats.get("avg_cost_usd", 0) or 0
            latency = runtime_stats.get("avg_latency_ms", 0) or 0
            tokens = runtime_stats.get("avg_tokens", 0) or 0

        return CostEstimate(
            cost_usd=float(cost),
            latency_ms=int(round(latency)),
            tokens=int(round(tokens)),
            confidence=confidence,
            source="historical",
        )

    # ── Default Estimation ──

    def _default_estimate(
        self,
        manifest: CapabilityManifest,
        adapter_name: str,
        input_size_chars: int,
    ) -> CostEstimate:
        """
        Estimate cost using embedded default pricing tables.

        Uses:
          - Characters → tokens: 1 char ~ 1.3 tokens (input).
          - Output token estimate: 30% of input (typical LLM output ratio).
          - Cost: (input_tokens / 1M * input_price + output_tokens / 1M * output_price).
          - Latency: base latency + total_tokens * 0.5 ms/token.

        Args:
            manifest: Capability manifest (used for name, cost hints).
            adapter_name: Adapter identifier for pricing lookup.
            input_size_chars: Input size in characters.

        Returns:
            A CostEstimate with source='default', confidence='low'.
        """
        model = self._resolve_model(adapter_name, manifest)
        pricing = self._resolve_pricing(adapter_name, model)
        base_latency = ADAPTER_BASE_LATENCY_MS.get(adapter_name, FALLBACK_LATENCY_MS)

        # Estimate tokens
        input_tokens = int(input_size_chars * 1.3)
        output_tokens = int(input_tokens * 0.3)
        total_tokens = input_tokens + output_tokens

        # Estimate cost
        if pricing is None:
            # Free tier or local (ollama, github-models)
            cost = 0.0
        else:
            cost = (
                input_tokens / 1_000_000 * pricing["input"]
                + output_tokens / 1_000_000 * pricing["output"]
            )

        # Estimate latency
        latency = int(base_latency + total_tokens * 0.5)

        return CostEstimate(
            cost_usd=cost,
            latency_ms=latency,
            tokens=total_tokens,
            confidence="low",
            source="default",
        )

    # ── Helpers ──

    def _resolve_model(
        self,
        adapter_name: str,
        manifest: CapabilityManifest,
    ) -> str:
        """
        Resolve the model name for a given adapter.

        Priority:
          1. Manifest's cost hint, if it names a known model.
          2. Adapter's default model.
          3. Fallback to 'gpt-4o'.
        """
        # Check manifest cost hints
        if manifest.cost and manifest.cost.pricing_hint:
            hint = manifest.cost.pricing_hint.strip().lower()
            # Pricing hint could be a model name like "gpt-4o" or
            # an adapter-qualified name like "openai/gpt-4o"
            #
            # Strategy: try exact match first, then substring match
            # (model name appears in the hint). Match longer model
            # names first so "gpt-4o-mini" beats "gpt-4o" when the
            # hint contains both.
            # NOTE: We check model-name-in-hint only, never the
            # reverse — that would let "gpt-4o" match "gpt-4o-mini".
            for known_model in sorted(MODEL_PRICING, key=len, reverse=True):
                km_lower = known_model.lower()
                if hint == km_lower or km_lower in hint:
                    return known_model

        return DEFAULT_MODELS.get(adapter_name, "gpt-4o")

    def _resolve_pricing(
        self,
        adapter_name: str,
        model: str,
    ) -> dict[str, float] | None:
        """
        Resolve pricing for a given adapter + model combination.

        Returns None for free/local tiers (cost = $0).
        """
        # Check adapter-specific pricing
        adapter_models = ADAPTER_PRICING.get(adapter_name)
        if adapter_models is not None:
            if not adapter_models:
                # Empty dict means free tier (ollama, github-models)
                return None
            if model in adapter_models:
                return adapter_models[model]

        # Fallback to global model pricing
        if model in MODEL_PRICING:
            return MODEL_PRICING[model]

        # Unknown model — use adapter default as proxy
        default_model = DEFAULT_MODELS.get(adapter_name)
        if default_model and default_model in MODEL_PRICING:
            return MODEL_PRICING[default_model]

        # Absolute fallback: openai/gpt-4o pricing
        return {"input": 2.50, "output": 10.00}

    def _derive_adapter(self, plan: Any) -> str:
        """
        Derive the most likely adapter name from a PlanResult.

        Currently returns 'openai' as default. Future versions will
        inspect matched capabilities or runtime preferences.
        """
        return "openai"

    @staticmethod
    def _aggregate_confidence(confidences: list[str]) -> str:
        """Combine confidence levels: lowest wins (conservative)."""
        if not confidences:
            return "low"
        if "low" in confidences:
            return "low"
        if "medium" in confidences:
            return "medium"
        return "high"
