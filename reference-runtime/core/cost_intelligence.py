"""
Intent OS — Cost Intelligence Engine (FinOps)

Analyzes API spending across agents, models, and execution patterns to
produce actionable cost-reduction recommendations. Every recommendation
includes SPECIFIC commands and dollar amounts — never vague guidance.

Built on top of the Event Store. Reads from both ``execution_records``
(persistent execution summaries) and proxy ``events`` (raw LLM telemetry).

Usage::

    store = EventStore("path/to/store.db")
    ci = CostIntelligence(store)

    report = ci.analyze()                        # all agents, 30 days
    report = ci.analyze(agent_id="agent_a82f")   # single agent
    projection = ci.predict_cost("agent_a82f", days=7)
    savings = ci.get_savings_opportunities("agent_a82f")
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from core.event_store import EventStore
from core.pricing import (
    CHEAPER_ALTERNATIVES,
    MODEL_CONTEXT_LIMITS,
    load_pricing,
    model_display_name,
)


# ---------------------------------------------------------------------------
# Pricing tables (externalized to core.pricing)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cutoff_iso(since_days: int) -> str:
    """ISO-8601 timestamp exactly *since_days* before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce *val* to float, returning *default* when it fails or is NaN."""
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """Coerce *val* to int, returning *default* on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# _model_display_name is now model_display_name from core.pricing


# ---------------------------------------------------------------------------
# CostIntelligence
# ---------------------------------------------------------------------------

class CostIntelligence:
    """
    FinOps cost analysis and optimization engine.

    Reads from the Event Store to produce:
      - Spending breakdowns by agent, model, and time period
      - Waste detection (duplicate calls, failed retries, oversized context)
      - Specific, actionable optimization recommendations with dollar amounts
      - Cost projections based on historical trends

    Every recommendation includes a concrete command the user can run
    and an estimated dollar savings.
    """

    __slots__ = ("_store",)

    def __init__(self, event_store: EventStore) -> None:
        self._store = event_store

    # ── Internal helpers ─────────────────────────────────────────────

    def _conn(self):
        """Thread-local SQLite connection."""
        return self._store.get_connection()

    def _build_agent_filter(self, agent_id: str | None) -> tuple[str, list[Any]]:
        """Return (where_clause, params) for agent filtering across tables."""
        if agent_id:
            return ("AND agent_id = ?", [agent_id])
        return ("", [])

    def _build_agent_proxy_filter(self, agent_id: str | None) -> tuple[str, list[Any]]:
        """Return (where_clause, params) for proxy event agent filtering."""
        if agent_id:
            return (
                "AND json_extract(payload, '$.source_agent') = ?",
                [agent_id],
            )
        return ("", [])

    # ──────────────────────────────────────────────────────────────────
    # analyze()
    # ──────────────────────────────────────────────────────────────────

    def analyze(
        self,
        agent_id: str | None = None,
        since_days: int = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Produce a comprehensive cost intelligence report.

        When *trace_id* is provided, returns a single-execution cost health
        analysis (backward-compatible with the v0.4 doctor command).
        When *trace_id* is None, returns the aggregate FinOps analysis.

        Args:
            agent_id: Optional agent to scope the aggregate analysis to.
            since_days: Lookback window in days (default 30).
            trace_id: Optional specific execution trace to analyze.

        Returns:
            When *trace_id* is provided:
              **trace_id**, **cost_usd**, **tokens**, **latency_ms**,
              **baseline_avg_cost**, **baseline_avg_latency**,
              **cost_vs_avg_pct**, **cost_health**, **optimization_tips**.

            When *trace_id* is None:
              **total_cost**, **daily_average**, **trend**,
              **trend_percentage**, **largest_single_cost**,
              **cost_by_model**, **cost_by_agent**, **waste_estimate**,
              **optimizations**.
        """
        if trace_id is not None:
            return self._analyze_single_execution(trace_id)

        cutoff = _cutoff_iso(since_days)
        conn = self._conn()
        ag_filter, ag_params = self._build_agent_filter(agent_id)
        px_filter, px_params = self._build_agent_proxy_filter(agent_id)

        # ── 1. Execution record cost/token aggregation ───────────────
        params_exec = [cutoff] + ag_params
        exec_rows = conn.execute(
            f"""SELECT
                  trace_id,
                  agent_id,
                  agent_name,
                  total_cost_usd,
                  total_tokens,
                  total_latency_ms,
                  status,
                  created_at,
                  manifest_name,
                  runtime_id
                FROM execution_records
                WHERE created_at >= ?
                  {ag_filter}
                ORDER BY created_at DESC""",
            params_exec,
        ).fetchall()

        # ── 2. Proxy event telemetry ──────────────────────────────────
        params_proxy = [cutoff] + px_params
        proxy_rows = conn.execute(
            f"""SELECT
                  trace_id,
                  json_extract(payload, '$.source_agent')  AS source_agent,
                  json_extract(payload, '$.model')          AS model,
                  CAST(json_extract(payload, '$.cost_usd')       AS REAL) AS cost_usd,
                  CAST(json_extract(payload, '$.input_tokens')   AS REAL) AS input_tokens,
                  CAST(json_extract(payload, '$.output_tokens')  AS REAL) AS output_tokens,
                  CAST(json_extract(payload, '$.total_tokens')   AS REAL) AS total_tokens,
                  CAST(json_extract(payload, '$.latency_ms')     AS REAL) AS latency_ms,
                  json_extract(payload, '$.status')         AS status,
                  json_extract(payload, '$.error')          AS error_msg,
                  timestamp
                FROM events
                WHERE source = 'proxy'
                  AND timestamp >= ?
                  {px_filter}
                ORDER BY timestamp DESC""",
            params_proxy,
        ).fetchall()

        # ── 3. Compute totals ─────────────────────────────────────────
        total_cost = 0.0
        total_tokens = 0
        total_calls = 0

        model_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "calls": 0,
                     "input_tokens": 0, "output_tokens": 0}
        )
        agent_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "calls": 0, "agent_name": ""}
        )
        daily_costs: dict[str, float] = defaultdict(float)

        largest: dict[str, Any] | None = None
        largest_cost = 0.0
        all_calls: list[dict[str, Any]] = []

        # ── 4. Process execution records ──────────────────────────────
        for row in exec_rows:
            cost = _safe_float(row["total_cost_usd"])
            tokens = _safe_int(row["total_tokens"])
            created = row["created_at"] or ""
            day = created[:10]
            status = row["status"] or "success"
            aid = row["agent_id"] or "unknown"
            aname = row["agent_name"] or aid
            tid = row["trace_id"] or ""

            total_cost += cost
            total_tokens += tokens
            total_calls += 1
            daily_costs[day] += cost

            agent_data[aid]["cost"] += cost
            agent_data[aid]["tokens"] += tokens
            agent_data[aid]["calls"] += 1
            agent_data[aid]["agent_name"] = aname

            if row["runtime_id"]:
                model_data[row["runtime_id"]]["cost"] += cost
                model_data[row["runtime_id"]]["tokens"] += tokens
                model_data[row["runtime_id"]]["calls"] += 1

            if cost > largest_cost:
                largest_cost = cost
                largest = {
                    "trace_id": tid,
                    "cost": round(cost, 6),
                    "agent_name": aname,
                    "what_happened": (
                        f"Execution of '{row['manifest_name'] or 'unknown'}' "
                        f"(status: {status}) — ran on {created[:10]}"
                    ),
                }

        # ── 5. Process proxy events ───────────────────────────────────
        for row in proxy_rows:
            cost = _safe_float(row["cost_usd"])
            tokens = _safe_int(row["total_tokens"])
            input_t = _safe_int(row["input_tokens"])
            output_t = _safe_int(row["output_tokens"])
            model = row["model"] or "unknown"
            status = row["status"] or "success"
            source_agent = row["source_agent"] or "unknown"
            ts = row["timestamp"] or ""
            day = ts[:10]

            total_cost += cost
            total_tokens += tokens
            total_calls += 1
            daily_costs[day] += cost

            agent_data[source_agent]["cost"] += cost
            agent_data[source_agent]["tokens"] += tokens
            agent_data[source_agent]["calls"] += 1
            if not agent_data[source_agent]["agent_name"]:
                agent_data[source_agent]["agent_name"] = source_agent

            model_data[model]["cost"] += cost
            model_data[model]["tokens"] += tokens
            model_data[model]["calls"] += 1
            model_data[model]["input_tokens"] += input_t
            model_data[model]["output_tokens"] += output_t

            if cost > largest_cost:
                largest_cost = cost
                largest = {
                    "trace_id": row["trace_id"] or "",
                    "cost": round(cost, 6),
                    "agent_name": source_agent,
                    "what_happened": (
                        f"LLM call to {model_display_name(model)} "
                        f"(input={input_t:,} tokens, output={output_t:,} tokens, "
                        f"status={status}) — on {ts[:10]}"
                    ),
                }

            all_calls.append({
                "trace_id": row["trace_id"],
                "model": model,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "total_tokens": tokens,
                "cost_usd": cost,
                "status": status,
                "source_agent": source_agent,
                "timestamp": ts,
                "error": row["error_msg"],
            })

        # ── 6. Cost by model (with percentages) ───────────────────────
        cost_by_model: list[dict[str, Any]] = []
        for model, data in sorted(model_data.items(), key=lambda x: -x[1]["cost"]):
            cost_by_model.append({
                "model": model,
                "cost": round(data["cost"], 6),
                "calls": data["calls"],
                "tokens": data["tokens"],
                "percentage": round(data["cost"] / max(total_cost, 0.000001) * 100, 1),
                "avg_input_tokens": round(data["input_tokens"] / max(data["calls"], 1)),
                "avg_output_tokens": round(data["output_tokens"] / max(data["calls"], 1)),
                "pricing": load_pricing().get(model),
            })

        # ── 7. Cost by agent (with percentages) ───────────────────────
        cost_by_agent: list[dict[str, Any]] = []
        for aid, data in sorted(agent_data.items(), key=lambda x: -x[1]["cost"]):
            cost_by_agent.append({
                "agent_id": aid,
                "agent_name": data["agent_name"],
                "cost": round(data["cost"], 6),
                "calls": data["calls"],
                "percentage": round(data["cost"] / max(total_cost, 0.000001) * 100, 1),
                "tokens": data["tokens"],
            })

        # ── 8. Trend computation ──────────────────────────────────────
        sorted_days = sorted(daily_costs.items())
        trend = "insufficient_data"
        trend_percentage = "0%"

        if len(sorted_days) >= 3:
            mid = len(sorted_days) // 2
            first_half = sorted_days[:mid]
            second_half = sorted_days[mid:]

            first_avg = sum(c for _, c in first_half) / max(len(first_half), 1)
            second_avg = sum(c for _, c in second_half) / max(len(second_half), 1)

            if first_avg > 0:
                change_pct = ((second_avg - first_avg) / first_avg) * 100
                if change_pct >= 0:
                    trend_percentage = f"+{change_pct:.1f}%"
                else:
                    trend_percentage = f"{change_pct:.1f}%"
                change = change_pct
            else:
                change = 100.0

            if change > 5:
                trend = "up"
            elif change < -5:
                trend = "down"
            else:
                trend = "stable"

        # ── 9. Daily average ──────────────────────────────────────────
        num_days = max(len(sorted_days), 1)
        daily_average = total_cost / num_days

        # ── 10. Waste estimate ────────────────────────────────────────
        waste = self._compute_waste(all_calls, exec_rows, total_cost)

        # ── 11. Optimizations ─────────────────────────────────────────
        optimizations = self._compute_optimizations(
            all_calls, model_data, agent_data, cost_by_model, cost_by_agent,
            total_cost, exec_rows,
        )

        return {
            "total_cost": round(total_cost, 4),
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "daily_average": round(daily_average, 4),
            "period_days": since_days,
            "trend": trend,
            "trend_percentage": trend_percentage,
            "largest_single_cost": largest,
            "cost_by_model": cost_by_model,
            "cost_by_agent": cost_by_agent,
            "waste_estimate": waste,
            "optimizations": optimizations,
        }

    # ──────────────────────────────────────────────────────────────────
    # Single-execution analysis (backward compat — doctor.py)
    # ──────────────────────────────────────────────────────────────────

    _COST_SPIKE_THRESHOLD = 2.0    # 2x average = warning
    _COST_CRITICAL_THRESHOLD = 5.0  # 5x average = concerning

    def _analyze_single_execution(self, trace_id: str) -> dict[str, Any]:
        """Per-trace cost health check. Used by ``doctor.py``."""
        record = self._store.get_record(trace_id)

        if not record:
            return {
                "trace_id": trace_id,
                "error": f"No execution record found for {trace_id}",
                "cost_health": "unknown",
            }

        manifest_name = record.get("manifest_name", "unknown")
        cost_usd = _safe_float(record.get("total_cost_usd"))
        tokens = _safe_int(record.get("total_tokens"))
        latency_ms = _safe_float(record.get("total_latency_ms"))

        # Compute baseline from sibling executions (same manifest, excluding self)
        siblings = self._store.query_records(
            manifest_name=manifest_name, limit=500)
        costs: list[float] = []
        latencies: list[float] = []
        for sib in siblings:
            if sib.get("trace_id") == trace_id:
                continue
            c = sib.get("total_cost_usd")
            if c is not None:
                costs.append(float(c))
            l = sib.get("total_latency_ms")
            if l is not None:
                latencies.append(float(l))

        baseline_cost = sum(costs) / len(costs) if costs else 0.0
        baseline_lat = sum(latencies) / len(latencies) if latencies else 0.0
        sibling_count = len(costs)

        cost_vs_avg_pct = 0.0
        if baseline_cost > 0 and cost_usd > 0:
            cost_vs_avg_pct = round(
                ((cost_usd - baseline_cost) / baseline_cost) * 100, 1)

        latency_vs_avg_pct = 0.0
        if baseline_lat > 0 and latency_ms > 0:
            latency_vs_avg_pct = round(
                ((latency_ms - baseline_lat) / baseline_lat) * 100, 1)

        # Cost health classification
        if sibling_count == 0:
            cost_health = "unknown (no baseline)"
        elif baseline_cost > 0:
            ratio = cost_usd / baseline_cost if baseline_cost > 0 else 0
            if ratio < 1.5:
                cost_health = "good"
            elif ratio < self._COST_CRITICAL_THRESHOLD:
                cost_health = "warning"
            else:
                cost_health = "concerning"
        else:
            cost_health = "good"  # zero-cost runs are fine

        # Optimization tips
        tips: list[str] = []
        if cost_vs_avg_pct > 50:
            tips.append(
                f"Cost is {cost_vs_avg_pct:.0f}% above average. "
                "Consider using a smaller model or reducing prompt length."
            )
        if latency_vs_avg_pct > 100:
            tips.append(
                f"Latency is {latency_vs_avg_pct:.0f}% above average. "
                "Check for network issues or try a faster model."
            )
        if tokens > 10000:
            tips.append(
                "High token count detected. Try caching repeated prompts "
                "or summarizing context before sending."
            )
        if cost_usd > 1.0:
            tips.append(
                "Cost exceeds $1.00 per run. For production workloads, "
                "consider self-hosted models (e.g. Ollama) to reduce cost."
            )
        if not tips:
            tips.append(
                "Cost is within normal range. No optimization needed.")

        return {
            "trace_id": trace_id,
            "manifest_name": manifest_name,
            "cost_usd": round(cost_usd, 6),
            "tokens": tokens,
            "latency_ms": round(latency_ms, 1),
            "baseline_avg_cost": round(baseline_cost, 6),
            "baseline_avg_latency": round(baseline_lat, 1),
            "baseline_sample_size": sibling_count,
            "cost_vs_avg_pct": cost_vs_avg_pct,
            "latency_vs_avg_pct": latency_vs_avg_pct,
            "cost_health": cost_health,
            "optimization_tips": tips,
        }

    # ──────────────────────────────────────────────────────────────────
    # Waste Estimation
    # ──────────────────────────────────────────────────────────────────

    def _compute_waste(
        self,
        all_calls: list[dict[str, Any]],
        exec_rows: list[Any],
        total_cost: float,
    ) -> dict[str, Any]:
        """
        Estimate wasted spend from:
          1. Failed calls (retries that failed)
          2. Duplicate/substantially-similar calls within 60s
          3. Near-context-limit calls (expensive on frontier models)
        """
        reasons: list[str] = []
        waste_amount = 0.0
        recommendations: list[str] = []

        # ── a) Failed calls cost (proxy events) ───────────────────────
        failed_cost = 0.0
        failed_count = 0
        for call in all_calls:
            if call["status"] == "failure":
                failed_cost += _safe_float(call["cost_usd"])
                failed_count += 1

        if failed_cost > 0:
            reasons.append(f"failed retries ({failed_count} failed calls)")
            waste_amount += failed_cost
            recommendations.append(
                f"Review {failed_count} failed API calls costing ${failed_cost:.4f}. "
                f"Common causes: invalid parameters, rate limiting, or model "
                f"unavailability. Fix root causes instead of letting retries "
                f"burn budget."
            )

        # Also count execution_record failures
        for row in exec_rows:
            status = row["status"] or ""
            if status in ("failure", "partial"):
                waste_amount += _safe_float(row["total_cost_usd"])

        # ── b) Duplicate calls (same model, similar tokens, within 60s) ──
        duplicate_cost = 0.0
        duplicate_pairs = 0
        sorted_calls = sorted(all_calls, key=lambda c: c["timestamp"] or "")
        for i in range(len(sorted_calls)):
            for j in range(i + 1, min(i + 50, len(sorted_calls))):
                ci = sorted_calls[i]
                cj = sorted_calls[j]
                try:
                    ti = datetime.fromisoformat(
                        ci["timestamp"].replace("Z", "+00:00"))
                    tj = datetime.fromisoformat(
                        cj["timestamp"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                if (tj - ti).total_seconds() > 60:
                    break

                if (
                    ci["model"] == cj["model"]
                    and ci["source_agent"] == cj["source_agent"]
                    and ci.get("trace_id") != cj.get("trace_id")
                ):
                    ti_tokens = ci.get("total_tokens", 0)
                    tj_tokens = cj.get("total_tokens", 0)
                    if max(ti_tokens, tj_tokens) > 0 and (
                        abs(ti_tokens - tj_tokens)
                        / max(ti_tokens, tj_tokens, 1) < 0.2
                    ):
                        duplicate_cost += min(
                            _safe_float(ci["cost_usd"]),
                            _safe_float(cj["cost_usd"]),
                        )
                        duplicate_pairs += 1

        if duplicate_pairs > 0:
            reasons.append(
                f"duplicate calls ({duplicate_pairs} near-identical pairs "
                f"within 60s)")
            waste_amount += duplicate_cost
            recommendations.append(
                f"Found {duplicate_pairs} pairs of nearly-identical calls "
                f"within 60 seconds (same model, same agent, same token "
                f"count). Estimated waste: ${duplicate_cost:.4f}. Implement "
                f"response caching or idempotency keys to prevent duplicate "
                f"API calls."
            )

        # ── c) Oversized context — calls near context limit ───────────
        oversized_count = 0
        oversized_cost = 0.0
        for call in all_calls:
            model = call.get("model", "")
            limit = MODEL_CONTEXT_LIMITS.get(model)
            total_t = call.get("total_tokens", 0)
            if limit and total_t > limit * 0.8:
                oversized_count += 1
                oversized_cost += _safe_float(call["cost_usd"]) * 0.3

        if oversized_count > 0:
            reasons.append(
                f"oversized context ({oversized_count} calls >80% of model "
                f"context limit)")
            waste_amount += oversized_cost
            recommendations.append(
                f"{oversized_count} calls exceed 80% of the model's context "
                f"window. Estimated waste from unnecessary context: "
                f"${oversized_cost:.4f}. Truncate chat history, use summary "
                f"compression, or reduce prompt templates. Set a max_tokens "
                f"limit appropriate to the task."
            )

        return {
            "amount": round(waste_amount, 4),
            "percentage_of_total": round(
                waste_amount / max(total_cost, 0.000001) * 100, 1),
            "reasons": reasons if reasons else ["no significant waste detected"],
            "savings_potential": round(waste_amount, 4),
            "recommendations": (
                recommendations
                if recommendations
                else [
                    "Current spending patterns look efficient. "
                    "Review again as usage scales."
                ]
            ),
        }

    # ──────────────────────────────────────────────────────────────────
    # Optimization Detection
    # ──────────────────────────────────────────────────────────────────

    def _compute_optimizations(
        self,
        all_calls: list[dict[str, Any]],
        model_data: dict[str, dict[str, Any]],
        agent_data: dict[str, dict[str, Any]],
        cost_by_model: list[dict[str, Any]],
        cost_by_agent: list[dict[str, Any]],
        total_cost: float,
        exec_rows: list[Any],
    ) -> list[dict[str, Any]]:
        """Generate specific, actionable optimization recommendations."""
        optimizations: list[dict[str, Any]] = []

        optimizations.extend(
            self._find_model_switch_opportunities(all_calls))
        optimizations.extend(
            self._find_context_reduction_opportunities(all_calls))
        optimizations.extend(self._find_batch_opportunities(all_calls))
        optimizations.extend(
            self._find_retry_fix_opportunities(all_calls, exec_rows))

        optimizations.sort(key=lambda x: -x["savings"])
        return optimizations

    def _find_model_switch_opportunities(
        self,
        all_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect opportunities to switch to cheaper models."""
        results: list[dict[str, Any]] = []

        agent_model_usage: dict[str, dict[str, list[dict[str, Any]]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        for call in all_calls:
            agent = call.get("source_agent", "unknown")
            model = call.get("model", "unknown")
            agent_model_usage[agent][model].append(call)

        for agent, models_used in agent_model_usage.items():
            for model, calls in models_used.items():
                alternatives = CHEAPER_ALTERNATIVES.get(model, [])
                if not alternatives:
                    continue

                current_cost = sum(
                    _safe_float(c["cost_usd"]) for c in calls)
                num_calls = len(calls)
                successes = sum(
                    1 for c in calls if c["status"] == "success")
                success_rate = successes / max(num_calls, 1)

                for alt_model, rationale in alternatives:
                    alt_pricing = load_pricing().get(alt_model)
                    if not alt_pricing:
                        continue

                    total_input = sum(
                        _safe_int(c.get("input_tokens", 0)) for c in calls)
                    total_output = sum(
                        _safe_int(c.get("output_tokens", 0)) for c in calls)

                    if total_input + total_output == 0:
                        projected_cost = current_cost * 0.3
                    else:
                        current_pricing = load_pricing().get(model)
                        if current_pricing:
                            projected_cost = (
                                total_input / 1_000_000 * alt_pricing["input"]
                                + total_output / 1_000_000
                                * alt_pricing["output"]
                            )
                        else:
                            projected_cost = current_cost * 0.5

                    savings = current_cost - projected_cost
                    if savings <= 0:
                        continue

                    export_var = ""
                    if alt_model.startswith("claude"):
                        export_var = f"export ANTHROPIC_MODEL={alt_model}"
                    elif alt_model.startswith("gpt") or alt_model.startswith("o"):
                        export_var = f"export OPENAI_MODEL={alt_model}"

                    how_to = (
                        f"Switch agent '{agent}' from "
                        f"{model_display_name(model)} to "
                        f"{model_display_name(alt_model)}. {rationale}. "
                        f"Run: {export_var}. "
                        f"Estimated savings: ${savings:.2f}/month "
                        f"({num_calls} calls, {success_rate:.0%} success rate "
                        f"on current model)."
                    )
                    if success_rate < 0.8:
                        how_to += (
                            f" NOTE: Current model has {success_rate:.0%} "
                            f"success rate — verify the cheaper model handles "
                            f"the same task quality before switching."
                        )

                    results.append({
                        "type": "model_switch",
                        "agent": agent,
                        "current_model": model,
                        "recommended_model": alt_model,
                        "current_cost": round(current_cost, 4),
                        "projected_cost": round(projected_cost, 4),
                        "savings": round(savings, 4),
                        "num_calls": num_calls,
                        "success_rate": round(success_rate, 2),
                        "export_command": export_var,
                        "how_to": how_to,
                    })
                    break

        return results

    def _find_context_reduction_opportunities(
        self,
        all_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect calls consistently near context limit."""
        results: list[dict[str, Any]] = []

        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for call in all_calls:
            model = call.get("model", "")
            if model:
                by_model[model].append(call)

        for model, calls in by_model.items():
            limit = MODEL_CONTEXT_LIMITS.get(model)
            if not limit:
                continue

            inputs = [
                _safe_int(c.get("input_tokens", 0))
                for c in calls
                if c.get("input_tokens")
            ]
            if not inputs:
                continue

            avg_input = statistics.mean(inputs)
            if avg_input > limit * 0.8:
                current_cost = sum(
                    _safe_float(c["cost_usd"]) for c in calls)
                projected_cost = current_cost * 0.75
                savings = current_cost - projected_cost

                how_to = (
                    f"Average input tokens ({int(avg_input):,}) exceed 80% of "
                    f"{model}'s context window ({limit:,}). Reduce "
                    f"prompt/context size by 50% to save ~${savings:.2f}. "
                    f"Techniques: (1) truncate conversation history to last "
                    f"10 messages, (2) compress tool output before re-feeding, "
                    f"(3) split large tasks into smaller sub-tasks. "
                    f"Run: Set max_history=10 in your agent config, or add a "
                    f"summary compression step before LLM calls."
                )

                results.append({
                    "type": "context_reduction",
                    "model": model,
                    "context_limit": limit,
                    "avg_input_tokens": int(avg_input),
                    "current_cost": round(current_cost, 4),
                    "projected_cost": round(projected_cost, 4),
                    "savings": round(savings, 4),
                    "num_calls": len(calls),
                    "how_to": how_to,
                })

        return results

    def _find_batch_opportunities(
        self,
        all_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Detect sequential calls to the same model that could be batched."""
        results: list[dict[str, Any]] = []

        if len(all_calls) < 2:
            return results

        sorted_calls = sorted(
            all_calls, key=lambda c: c.get("timestamp") or "")

        burst_threshold_seconds = 5
        min_burst_size = 3

        current_burst: list[dict[str, Any]] = []
        for call in sorted_calls:
            if not current_burst:
                current_burst.append(call)
                continue

            prev = current_burst[-1]
            try:
                pt = datetime.fromisoformat(
                    prev["timestamp"].replace("Z", "+00:00"))
                ct = datetime.fromisoformat(
                    call["timestamp"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                current_burst = [call]
                continue

            same_model = call.get("model") == prev.get("model")
            same_agent = (
                call.get("source_agent") == prev.get("source_agent"))
            within_window = (
                (ct - pt).total_seconds() <= burst_threshold_seconds)

            if same_model and same_agent and within_window:
                current_burst.append(call)
            else:
                if len(current_burst) >= min_burst_size:
                    burst_cost = sum(
                        _safe_float(c["cost_usd"]) for c in current_burst)
                    savings = burst_cost * 0.15

                    model = current_burst[0].get("model", "unknown")
                    agent = current_burst[0].get("source_agent", "unknown")

                    how_to = (
                        f"Found {len(current_burst)} sequential calls to "
                        f"{model} by agent '{agent}' within "
                        f"{burst_threshold_seconds}s of each other. Batch "
                        f"these into a single multi-turn call instead. "
                        f"Savings from eliminating redundant system prompts "
                        f"and connection overhead: ~${savings:.4f}. "
                        f"How: Pre-collect prompts, send as a batch array, "
                        f"process results together. This avoids "
                        f"{len(current_burst) - 1} redundant system prompt "
                        f"charges."
                    )

                    results.append({
                        "type": "batch_merge",
                        "model": model,
                        "agent": agent,
                        "burst_size": len(current_burst),
                        "burst_cost": round(burst_cost, 4),
                        "savings": round(savings, 4),
                        "how_to": how_to,
                    })
                current_burst = [call]

        return results

    def _find_retry_fix_opportunities(
        self,
        all_calls: list[dict[str, Any]],
        exec_rows: list[Any],
    ) -> list[dict[str, Any]]:
        """Detect high retry rates and recommend root-cause fixes."""
        results: list[dict[str, Any]] = []

        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for call in all_calls:
            agent = call.get("source_agent", "unknown")
            by_agent[agent].append(call)

        for agent, calls in by_agent.items():
            total = len(calls)
            if total == 0:
                continue

            failures = [c for c in calls if c.get("status") == "failure"]
            failure_rate = len(failures) / total

            if failure_rate > 0.2:
                failed_cost = sum(
                    _safe_float(c["cost_usd"]) for c in failures)
                savings = failed_cost * 0.8

                error_types: dict[str, int] = defaultdict(int)
                for f in failures:
                    err = str(f.get("error") or "unknown").lower()
                    if "rate" in err or "429" in err:
                        error_types["rate_limit"] += 1
                    elif "timeout" in err:
                        error_types["timeout"] += 1
                    elif "auth" in err or "401" in err or "403" in err:
                        error_types["auth"] += 1
                    elif "context" in err or "token" in err:
                        error_types["context_limit"] += 1
                    else:
                        error_types["other"] += 1

                top_error = (
                    max(error_types, key=error_types.get)
                    if error_types
                    else "unknown"
                )
                error_count = error_types[top_error]
                error_pct = error_count / max(len(failures), 1) * 100

                fix_commands: dict[str, str] = {
                    "rate_limit": (
                        "Add exponential backoff and rate-limit awareness. "
                        "Run: Reduce max_concurrency=1, add "
                        "retry_delay=5000ms"
                    ),
                    "timeout": (
                        "Increase timeout or split large requests. "
                        "Run: Set request_timeout=120000ms, or reduce "
                        "input size"
                    ),
                    "auth": (
                        "Fix API key or token configuration. "
                        "Run: Verify ANTHROPIC_API_KEY / OPENAI_API_KEY "
                        "are valid"
                    ),
                    "context_limit": (
                        "Truncate input to fit model context window. "
                        "Run: Set max_input_tokens=80000, enable "
                        "auto-truncation"
                    ),
                    "other": (
                        "Investigate error patterns and fix root causes. "
                        "Review error messages and retry logic."
                    ),
                }

                how_to = (
                    f"Agent '{agent}' has a {failure_rate:.0%} failure rate "
                    f"({len(failures)}/{total} calls fail). Top error "
                    f"category: '{top_error}' ({error_pct:.0f}% of "
                    f"failures). Fixing this saves ~${savings:.4f} in "
                    f"wasted retry spend. "
                    f"{fix_commands.get(top_error, fix_commands['other'])}"
                )

                results.append({
                    "type": "retry_fix",
                    "agent": agent,
                    "total_calls": total,
                    "failure_count": len(failures),
                    "failure_rate": round(failure_rate, 2),
                    "top_error_category": top_error,
                    "current_cost": round(failed_cost, 4),
                    "projected_cost": round(failed_cost * 0.2, 4),
                    "savings": round(savings, 4),
                    "how_to": how_to,
                })

        return results

    # ──────────────────────────────────────────────────────────────────
    # predict_cost()
    # ──────────────────────────────────────────────────────────────────

    def predict_cost(
        self,
        agent_id: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """
        Project future cost based on historical trend.

        Uses linear regression on daily cost data over the last 30 days
        to project the next *days* days.

        Args:
            agent_id: Optional agent to scope projection to.
            days: Number of days to project forward (default: 7).

        Returns:
            Dict with **projected_total**, **confidence**,
            **trend_direction**, **projected_daily_breakdown**, **method**,
            **baseline_period_days**.
        """
        cutoff = _cutoff_iso(30)
        conn = self._conn()
        ag_filter, ag_params = self._build_agent_filter(agent_id)
        px_filter, px_params = self._build_agent_proxy_filter(agent_id)

        params_exec = [cutoff] + ag_params
        exec_daily = conn.execute(
            f"""SELECT
                  DATE(created_at)                     AS day,
                  COALESCE(SUM(total_cost_usd), 0)     AS daily_cost,
                  COUNT(*)                             AS call_count
                FROM execution_records
                WHERE created_at >= ?
                  {ag_filter}
                GROUP BY DATE(created_at)
                ORDER BY day ASC""",
            params_exec,
        ).fetchall()

        params_proxy = [cutoff] + px_params
        proxy_daily = conn.execute(
            f"""SELECT
                  DATE(timestamp)                               AS day,
                  COALESCE(SUM(CAST(
                    json_extract(payload, '$.cost_usd') AS REAL)), 0) AS daily_cost,
                  COUNT(*)                                      AS call_count
                FROM events
                WHERE source = 'proxy'
                  AND timestamp >= ?
                  {px_filter}
                GROUP BY DATE(timestamp)
                ORDER BY day ASC""",
            params_proxy,
        ).fetchall()

        # Merge daily costs
        daily_map: dict[str, dict[str, float]] = defaultdict(
            lambda: {"cost": 0.0, "calls": 0})
        for row in exec_daily:
            daily_map[row["day"]]["cost"] += _safe_float(row["daily_cost"])
            daily_map[row["day"]]["calls"] += _safe_int(row["call_count"])
        for row in proxy_daily:
            daily_map[row["day"]]["cost"] += _safe_float(row["daily_cost"])
            daily_map[row["day"]]["calls"] += _safe_int(row["call_count"])

        sorted_days = sorted(daily_map.items())

        if len(sorted_days) < 2:
            fallback = 0.0
            if sorted_days:
                fallback = daily_map[sorted_days[0][0]]["cost"] * days
            return {
                "projected_total": round(fallback, 4),
                "confidence": "low",
                "trend_direction": "insufficient_data",
                "projected_daily_breakdown": [],
                "method": "simple_average",
                "baseline_period_days": len(sorted_days),
                "projection_days": days,
            }

        xs = list(range(len(sorted_days)))
        ys = [data["cost"] for _, data in sorted_days]

        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_xx = sum(x * x for x in xs)

        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            avg_daily = sum_y / n
            return {
                "projected_total": round(avg_daily * days, 4),
                "confidence": "high",
                "trend_direction": "stable",
                "projected_daily_breakdown": [
                    {"day": d + 1, "projected_cost": round(avg_daily, 4)}
                    for d in range(days)
                ],
                "method": "flat_projection",
                "baseline_period_days": n,
                "projection_days": days,
            }

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        y_mean = sum_y / n
        ss_res = sum(
            (y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        ss_tot = sum((y - y_mean) ** 2 for y in ys)
        r_squared = 1 - (ss_res / max(ss_tot, 0.000001))
        r_squared = max(0.0, min(1.0, r_squared))

        if r_squared > 0.7:
            confidence = "high"
        elif r_squared > 0.4:
            confidence = "medium"
        else:
            confidence = "low"

        projected_daily: list[dict[str, Any]] = []
        projected_total = 0.0
        for d in range(days):
            idx = n + d
            projected = max(0.0, slope * idx + intercept)
            projected_daily.append({
                "day": d + 1,
                "projected_cost": round(projected, 4),
            })
            projected_total += projected

        if slope > 0.01:
            trend_direction = "up"
        elif slope < -0.01:
            trend_direction = "down"
        else:
            trend_direction = "stable"

        return {
            "projected_total": round(projected_total, 4),
            "daily_average_projected": round(projected_total / days, 4),
            "confidence": confidence,
            "r_squared": round(r_squared, 3),
            "trend_direction": trend_direction,
            "projected_daily_breakdown": projected_daily,
            "slope": round(slope, 6),
            "method": "linear_regression",
            "baseline_period_days": n,
            "projection_days": days,
        }

    # ──────────────────────────────────────────────────────────────────
    # get_savings_opportunities()
    # ──────────────────────────────────────────────────────────────────

    def get_savings_opportunities(
        self,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return a ranked list of specific money-saving actions.

        Each item includes precise dollar amounts and the command to execute.

        Returns:
            List of dicts, each with: **action**, **current_monthly_cost**,
            **projected_monthly_cost**, **savings**, **difficulty**,
            **payoff_days**, **priority**, **how_to**.
        """
        analysis = self.analyze(agent_id=agent_id, since_days=30)
        opportunities: list[dict[str, Any]] = []

        for opt in analysis.get("optimizations", []):
            current_monthly = opt["current_cost"]
            projected_monthly = opt["projected_cost"]
            savings = opt["savings"]

            if opt["type"] == "model_switch":
                difficulty = "easy"
                action = (
                    f"Switch from {opt.get('current_model', '')} to "
                    f"{opt.get('recommended_model', '')} for agent "
                    f"'{opt.get('agent', '')}'"
                )
            elif opt["type"] == "context_reduction":
                difficulty = "medium"
                action = (
                    f"Reduce context/prompt size for {opt.get('model', '')} "
                    f"(avg {opt.get('avg_input_tokens', 0):,} tokens -> "
                    f"below {opt.get('context_limit', 0) * 0.5:,.0f} tokens)"
                )
            elif opt["type"] == "batch_merge":
                difficulty = "medium"
                action = (
                    f"Batch {opt.get('burst_size', 0)} sequential LLM calls "
                    f"into single multi-turn request for agent "
                    f"'{opt.get('agent', '')}'"
                )
            elif opt["type"] == "retry_fix":
                difficulty = "medium"
                action = (
                    f"Fix root cause of {opt.get('failure_rate', 0):.0%} "
                    f"failure rate for agent '{opt.get('agent', '')}' "
                    f"({opt.get('top_error_category', '')})"
                )
            else:
                difficulty = "medium"
                action = opt.get("how_to", "")[:120]

            opportunities.append({
                "action": action,
                "current_monthly_cost": round(current_monthly, 4),
                "projected_monthly_cost": round(projected_monthly, 4),
                "savings": round(savings, 4),
                "difficulty": difficulty,
                "payoff_days": 0,
                "priority": _priority_score(savings, difficulty),
                "how_to": opt.get("how_to", ""),
            })

        # Add waste savings
        waste = analysis.get("waste_estimate", {})
        if waste.get("amount", 0) > 0.01:
            opportunities.append({
                "action": "Eliminate estimated waste spend",
                "current_monthly_cost": round(waste["amount"], 4),
                "projected_monthly_cost": round(waste["amount"] * 0.2, 4),
                "savings": round(waste["amount"] * 0.8, 4),
                "difficulty": "easy",
                "payoff_days": 0,
                "priority": "★★★ CRITICAL",
                "how_to": (
                    f"Waste details: "
                    f"{', '.join(waste.get('reasons', ['unknown']))}. "
                    f"{'; '.join(waste.get('recommendations', []))}"
                ),
            })

        # Per-model pricing awareness (>10% of spend)
        for model_entry in analysis.get("cost_by_model", []):
            model = model_entry["model"]
            pricing = load_pricing().get(model)
            if pricing and model_entry["percentage"] > 10:
                alternatives = CHEAPER_ALTERNATIVES.get(model, [])
                if alternatives:
                    alt_model, rationale = alternatives[0]
                    alt_price = load_pricing().get(alt_model, {})
                    if alt_price:
                        current_monthly = model_entry["cost"]
                        ratio = (
                            pricing["input"]
                            / max(alt_price.get("input", 0.01), 0.001))
                        projected = current_monthly / max(ratio, 1.0)
                        savings = current_monthly - projected

                        if savings > 0.01:
                            export_cmd = ""
                            if alt_model.startswith("claude"):
                                export_cmd = (
                                    f"export ANTHROPIC_MODEL={alt_model}")
                            else:
                                export_cmd = (
                                    f"export OPENAI_MODEL={alt_model}")

                            opportunities.append({
                                "action": (
                                    f"Replace {model_display_name(model)} "
                                    f"with {model_display_name(alt_model)} "
                                    f"({model_entry['percentage']:.0f}% of "
                                    f"spend)"
                                ),
                                "current_monthly_cost": round(
                                    current_monthly, 4),
                                "projected_monthly_cost": round(
                                    projected, 4),
                                "savings": round(savings, 4),
                                "difficulty": "easy",
                                "payoff_days": 0,
                                "priority": _priority_score(savings, "easy"),
                                "how_to": (
                                    f"{rationale}. Run: {export_cmd}. "
                                    f"Estimated savings: ${savings:.2f}/month "
                                    f"({model_entry['calls']} calls in 30 "
                                    f"days)."
                                ),
                            })

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for opp in opportunities:
            key = opp["action"][:80]
            if key not in seen:
                seen.add(key)
                unique.append(opp)

        unique.sort(key=lambda o: -o["savings"])
        return unique


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

def _priority_score(savings: float, difficulty: str) -> str:
    """Convert savings + difficulty into a star rating."""
    diff_mult = {"easy": 1.5, "medium": 1.0, "hard": 0.5}.get(difficulty, 1.0)
    score = savings * diff_mult

    if score > 5.0:
        return "★★★ CRITICAL"
    elif score > 1.0:
        return "★★ HIGH"
    elif score > 0.1:
        return "★ MEDIUM"
    else:
        return "LOW"


# ---------------------------------------------------------------------------
# Convenience: full FinOps report
# ---------------------------------------------------------------------------

def generate_finops_report(
    event_store: EventStore,
    agent_id: str | None = None,
    since_days: int = 30,
) -> dict[str, Any]:
    """
    One-shot convenience that returns the complete FinOps picture.

    Bundles :meth:`CostIntelligence.analyze`,
    :meth:`CostIntelligence.predict_cost`, and
    :meth:`CostIntelligence.get_savings_opportunities`.

    Returns a dict with keys: **analyze**, **predict_cost**,
    **savings_opportunities**, **generated_at**.
    """
    ci = CostIntelligence(event_store)
    return {
        "analyze": ci.analyze(agent_id=agent_id, since_days=since_days),
        "predict_cost": ci.predict_cost(agent_id=agent_id, days=7),
        "savings_opportunities": ci.get_savings_opportunities(
            agent_id=agent_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
