"""
Intent OS - Agent Failure Intelligence Engine (Blueprint Phase 2.3)

Production-grade failure diagnosis, classification, and taxonomy engine.

Built on Event Store and Experience Store data. Provides:
  - Root-cause diagnosis of single or aggregate agent failures
  - Multi-signal failure classification into a 7-type taxonomy
  - Trend-aware failure aggregation with actionable remediation

Every recommendation is SPECIFIC and ACTIONABLE - it names the exact
parameter, file, model, or command the user should change. Never vague.

Usage::

    from core.event_store import EventStore
    from core.experience_store import ExperienceStore
    from core.failure_intelligence import FailureIntelligence

    fi = FailureIntelligence(event_store, experience_store)

    # Diagnose a single failed execution
    report = fi.diagnose(trace_id="abc-123")

    # Diagnose all recent failures for an agent
    report = fi.diagnose(agent_id="agent_a82f91c3")

    # Classify a raw failure
    result = fi.classify_failure(
        error_type="RuntimeError",
        error_message="Connection timed out after 30s",
        capability="text_summarize@1.0",
        latency=30100,
        tokens=4500,
    )

    # Aggregate failure taxonomy
    taxonomy = fi.get_failure_taxonomy(agent_id="agent_a82f91c3", since_days=30)
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from core.event_store import EventStore
from core.experience_store import ExperienceStore


# ================================================================
# Constants
# ================================================================

# Known model context window sizes (tokens) - updated 2026-07
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Anthropic Claude family
    "claude": 200_000,
    "claude-3": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5": 200_000,
    "claude-3.5-sonnet": 200_000,
    "claude-3.5-haiku": 200_000,
    "claude-4": 200_000,
    "claude-4-opus": 200_000,
    "claude-4-sonnet": 200_000,
    "claude-4-haiku": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-opus-4": 200_000,
    "claude-opus-4-8": 1_000_000,
    # OpenAI GPT family
    "gpt-4": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.5": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-3.5": 16_385,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5-turbo-16k": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    # Google Gemini family
    "gemini": 1_048_576,
    "gemini-1.5": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2": 1_048_576,
    "gemini-2.0": 1_048_576,
    "gemini-2.5": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    # Open-weight models
    "llama": 128_000,
    "llama-3": 128_000,
    "llama-3.1": 128_000,
    "llama-3.2": 128_000,
    "llama-3.3": 128_000,
    "llama-4": 128_000,
    "mixtral": 32_768,
    "mistral": 32_768,
    "mistral-large": 128_000,
    "deepseek": 128_000,
    "deepseek-v3": 128_000,
    "deepseek-r1": 128_000,
    "qwen": 131_072,
    "qwen-2.5": 131_072,
}

_CONTEXT_OVERFLOW_THRESHOLD = 0.85
_MIN_EXECUTIONS_FOR_TREND = 5
_MAX_SIMILAR_FAILURES = 5
_MAX_TAXONOMY_TYPES = 20

_CONTEXT_UPGRADE_SUGGESTIONS: list[dict[str, str]] = [
    {
        "match": "claude",
        "suggestion": "claude-opus-4-8",
        "limit": "1,000,000 tokens",
        "how": (
            "Set runtime_id to 'claude-opus-4-8' in your capability manifest or "
            "export INTENT_OS_DEFAULT_MODEL=claude-opus-4-8"
        ),
    },
    {
        "match": "gpt-4",
        "suggestion": "gpt-4.1",
        "limit": "1,000,000 tokens",
        "how": (
            "Set runtime_id to 'gpt-4.1' in your capability manifest or "
            "export INTENT_OS_DEFAULT_MODEL=gpt-4.1"
        ),
    },
    {
        "match": "gpt-3",
        "suggestion": "gpt-4.1",
        "limit": "1,000,000 tokens",
        "how": (
            "Set runtime_id to 'gpt-4.1' in your capability manifest or "
            "export INTENT_OS_DEFAULT_MODEL=gpt-4.1"
        ),
    },
    {
        "match": "gemini",
        "suggestion": "gemini-2.5-pro",
        "limit": "1,048,576 tokens",
        "how": (
            "Set runtime_id to 'gemini-2.5-pro' in your capability manifest or "
            "export INTENT_OS_DEFAULT_MODEL=gemini-2.5-pro"
        ),
    },
    {
        "match": "llama",
        "suggestion": "claude-sonnet-4",
        "limit": "200,000 tokens",
        "how": (
            "Set runtime_id to 'claude-sonnet-4' in your capability manifest or "
            "export INTENT_OS_DEFAULT_MODEL=claude-sonnet-4"
        ),
    },
]


# ================================================================
# Helpers
# ================================================================

def _cutoff_iso(since_days: int) -> str:
    """Return an ISO-8601 timestamp *since_days* before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()


def _safe_round(value: float | None, ndigits: int = 4) -> float:
    """Round *value*, returning 0.0 when *value* is None."""
    if value is None:
        return 0.0
    return round(float(value), ndigits)


def _parse_json_cell(raw: str | None) -> dict[str, Any]:
    """Safely parse a JSON cell, returning ``{}`` on failure."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _resolve_context_limit(runtime_id: str | None) -> tuple[int, str]:
    """Return (token_limit, matched_key) for a runtime_id.

    Does substring matching against the known model map.  Returns
    (200_000, "default") when no match is found.
    """
    if not runtime_id:
        return 200_000, "default"
    rid = runtime_id.lower().strip()
    for key in sorted(_MODEL_CONTEXT_LIMITS, key=len, reverse=True):
        if key in rid:
            return _MODEL_CONTEXT_LIMITS[key], key
    return 200_000, "default"


def _upgrade_suggestion(runtime_id: str | None) -> dict[str, str] | None:
    """Return a concrete model-upgrade suggestion dict, or None."""
    if not runtime_id:
        return _CONTEXT_UPGRADE_SUGGESTIONS[1]
    rid = runtime_id.lower().strip()
    for entry in _CONTEXT_UPGRADE_SUGGESTIONS:
        if entry["match"] in rid:
            return entry
    return _CONTEXT_UPGRADE_SUGGESTIONS[1]


def _extract_failure_pattern(error_message: str) -> str:
    """Normalize an error message into a fingerprint for deduplication.

    Strips variable parts like timestamps, IDs, hex strings, and
    file paths so that semantically identical errors hash together.
    """
    msg = error_message or ""
    msg = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
        "<TS>", msg,
    )
    msg = re.sub(r"\b\d{10,13}\b", "<UNIX_TS>", msg)
    msg = re.sub(r"\b[0-9a-fA-F]{9,}\b", "<HEX>", msg)
    msg = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "<UUID>", msg,
    )
    msg = re.sub(r"(?:/[^\s:,]+)+/[^\s:,]+", "<PATH>", msg)
    msg = re.sub(r"[A-Za-z]:\\[^\s:,]+(?:\\[^\s:,]+)*", "<PATH>", msg)
    msg = re.sub(r"https?://[^\s]+", "<URL>", msg)
    msg = re.sub(r"\s+", " ", msg).strip().lower()
    return msg[:200]


# ================================================================
# FailureIntelligence
# ================================================================

class FailureIntelligence:
    """Agent Failure Intelligence Engine.

    Wraps an :class:`EventStore` and :class:`ExperienceStore` to
    diagnose, classify, and aggregate agent execution failures.

    All public methods are read-only - they never mutate the stores.
    """

    __slots__ = ("_store", "_exp_store")

    def __init__(
        self,
        event_store: EventStore,
        experience_store: ExperienceStore,
    ) -> None:
        self._store = event_store
        self._exp_store = experience_store

    def _conn(self):
        """Thread-local SQLite connection from the backing EventStore."""
        return self._store.get_connection()

    # ============================================================
    # classify_failure
    # ============================================================

    def classify_failure(
        self,
        error_type: str = "",
        error_message: str = "",
        capability: str = "",
        latency: float = 0.0,
        tokens: int = 0,
        runtime_id: str = "",
    ) -> dict[str, Any]:
        """Classify a single failure into the 7-type taxonomy.

        Args:
            error_type: The raw error type / exception class name.
            error_message: The full error message string.
            capability: The capability name@version being executed.
            latency: Total latency in milliseconds.
            tokens: Total tokens consumed in the execution.
            runtime_id: The model / runtime identifier.

        Returns:
            A dict with ``type``, ``confidence``, and ``explanation``.
        """
        err = (error_message or "").lower().strip()
        etype = (error_type or "").lower().strip()
        limit, _matched_key = _resolve_context_limit(runtime_id)

        checks: list[tuple[str, float, str]] = []

        # 1. Rate limit
        rate_signals = 0
        if "rate limit" in err or "rate_limit" in err:
            rate_signals += 2
        if "429" in err or "too many requests" in err:
            rate_signals += 2
        if "quota" in err and ("exceed" in err or "limit" in err):
            rate_signals += 1
        if "throttl" in err:
            rate_signals += 2
        if "retry after" in err or "retry-after" in err:
            rate_signals += 1
        if "rate" in etype and "limit" in etype:
            rate_signals += 1
        if rate_signals >= 2:
            checks.append((
                "rate_limit",
                min(_safe_round(rate_signals / 4, 2), 1.0),
                f"API rate limit hit - {rate_signals} rate-limit indicators",
            ))

        # 2. Permission denied
        perm_signals = 0
        if "permission" in err and ("denied" in err or "error" in err):
            perm_signals += 2
        if "forbidden" in err or "403" in err:
            perm_signals += 2
        if "unauthorized" in err or "401" in err:
            perm_signals += 2
        if "access denied" in err:
            perm_signals += 2
        if "not allowed" in err:
            perm_signals += 1
        if "permission" in etype or "denied" in etype:
            perm_signals += 1
        if perm_signals >= 2:
            checks.append((
                "permission_denied",
                min(_safe_round(perm_signals / 4, 2), 1.0),
                f"Permission/authorization error - {perm_signals} indicators",
            ))

        # 3. Timeout
        timeout_signals = 0
        if "timeout" in err or "timed out" in err or "timed-out" in err:
            timeout_signals += 2
        if "deadline exceeded" in err:
            timeout_signals += 2
        if "timed" in etype or "timeout" in etype:
            timeout_signals += 1
        if latency > 300_000:
            timeout_signals += 1
        if "connection" in err and ("reset" in err or "refused" in err):
            timeout_signals += 1
        if timeout_signals >= 2:
            checks.append((
                "timeout",
                min(_safe_round(timeout_signals / 4, 2), 1.0),
                f"Timeout detected - {timeout_signals} indicators, "
                f"latency was {latency:.0f}ms",
            ))

        # 4. Context overflow
        ctx_signals = 0
        token_ratio = tokens / max(limit, 1)
        if token_ratio >= _CONTEXT_OVERFLOW_THRESHOLD:
            ctx_signals += 3
        elif token_ratio >= 0.70:
            ctx_signals += 1
        if "context" in err and ("length" in err or "token" in err or "limit" in err):
            ctx_signals += 2
        if "token" in err and ("exceed" in err or "limit" in err or "maximum" in err):
            ctx_signals += 2
        if "too long" in err or "too many token" in err:
            ctx_signals += 2
        if "reduce" in err and ("length" in err or "size" in err or "input" in err):
            ctx_signals += 1
        if "truncat" in err:
            ctx_signals += 1
        if ctx_signals >= 2:
            checks.append((
                "context_overflow",
                min(_safe_round(ctx_signals / 5, 2), 1.0),
                f"Context overflow - {tokens} tokens used "
                f"({token_ratio:.0%} of {limit} limit for "
                f"{runtime_id or 'unknown model'}), "
                f"{ctx_signals} signals",
            ))

        # 5. Tool failure
        tool_signals = 0
        if "tool" in err:
            tool_signals += 2
        if "function" in err and ("call" in err or "not found" in err or "invalid" in err):
            tool_signals += 1
        if "execution" in err and "failed" in err:
            tool_signals += 1
        if "command" in err and ("failed" in err or "not found" in err):
            tool_signals += 1
        if "api" in err and ("error" in err or "fail" in err):
            tool_signals += 1
        if "module" in err and ("not found" in err or "no module" in err):
            tool_signals += 1
        if "import" in err and "error" in err:
            tool_signals += 1
        if tool_signals >= 2:
            checks.append((
                "tool_failure",
                min(_safe_round(tool_signals / 4, 2), 1.0),
                f"Tool/function execution failure - {tool_signals} tool-error indicators",
            ))

        # 6. Model hallucination
        hallu_signals = 0
        if "not found" in err and ("tool" in err or "function" in err or "resource" in err):
            hallu_signals += 2
        if "does not exist" in err:
            hallu_signals += 1
        if "no such" in err:
            hallu_signals += 1
        if "invalid" in err and ("tool" in err or "function" in err or "parameter" in err):
            hallu_signals += 1
        if "hallucin" in err:
            hallu_signals += 3
        if "fabricat" in err or "made up" in err:
            hallu_signals += 2
        if (not err) and (not etype) and tokens < 50:
            hallu_signals += 1
        if hallu_signals >= 2:
            checks.append((
                "model_hallucination",
                min(_safe_round(hallu_signals / 4, 2), 1.0),
                f"Model hallucination - {hallu_signals} indicators",
            ))

        # 7. Reasoning error (catch-all)
        reason_signals = 0
        if "invalid" in err:
            reason_signals += 1
        if "error" in err and not checks:
            reason_signals += 1
        if "unexpected" in err:
            reason_signals += 1
        if "type" in err and "error" in err:
            reason_signals += 1
        if "attribute" in err and "error" in err:
            reason_signals += 1
        if "key" in err and "error" in err:
            reason_signals += 1
        if "value" in err and "error" in err:
            reason_signals += 1
        if "assertion" in err:
            reason_signals += 1
        if reason_signals >= 1:
            checks.append((
                "reasoning_error",
                min(_safe_round(reason_signals / 3, 2), 0.65),
                "Likely reasoning/logic error - model produced invalid output",
            ))

        # Return best match
        if checks:
            checks.sort(key=lambda c: (-c[1], c[0] != "reasoning_error"))
            best = checks[0]
            return {
                "type": best[0],
                "confidence": best[1],
                "explanation": best[2],
            }

        return {
            "type": "unknown",
            "confidence": 0.3,
            "explanation": (
                f"No strong signal matched. Error type='{error_type}', "
                f"message preview='{(error_message or '')[:120]}'"
            ),
        }

    # ============================================================
    # diagnose
    # ============================================================

    def diagnose(
        self,
        agent_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Diagnose the root cause of one or more agent failures.

        Dispatch: trace_id > agent_id > latest failure overall.

        Returns a dict with: verdict, confidence, root_cause_type,
        evidence, fix_suggestion, estimated_success_improvement,
        similar_past_failures.
        """
        if trace_id:
            return self._diagnose_single(trace_id)
        if agent_id:
            return self._diagnose_agent_aggregate(agent_id)
        return self._diagnose_latest()

    def _diagnose_single(self, trace_id: str) -> dict[str, Any]:
        """Deep-dive diagnosis of a single failed execution."""
        record = self._store.get_record(trace_id)
        events = self._store.get_events_by_trace(trace_id)

        if record is None:
            return {
                "verdict": f"No execution record found for trace_id='{trace_id}'.",
                "confidence": 0.0,
                "root_cause_type": "unknown",
                "evidence": [],
                "fix_suggestion": "Verify the trace_id exists: intent-os inspect list",
                "estimated_success_improvement": "0%",
                "similar_past_failures": [],
            }

        status = record.get("status", "")
        if status not in ("failure", "partial"):
            return {
                "verdict": (
                    f"Execution {trace_id} has status '{status}', "
                    f"not a failure. No diagnosis needed."
                ),
                "confidence": 1.0,
                "root_cause_type": "unknown",
                "evidence": [f"Status: {status}"],
                "fix_suggestion": "No fix needed.",
                "estimated_success_improvement": "0%",
                "similar_past_failures": [],
            }

        evidence: list[str] = []
        failed_events: list[dict[str, Any]] = []
        all_errors: list[str] = []
        all_error_types: list[str] = []
        task_attempts: Counter[str] = Counter()

        for evt in events:
            etype = evt.get("event_type", "")
            task_id_val = evt.get("task_id", "")
            if task_id_val:
                task_attempts[task_id_val] += 1
            if etype in ("TaskFailed", "WorkflowFailed"):
                failed_events.append(evt)
                payload = _parse_json_cell(evt.get("payload"))
                err_msg = (
                    payload.get("error_message")
                    or payload.get("error")
                    or evt.get("error", "")
                )
                err_type = payload.get("error_type", "")
                if err_msg:
                    all_errors.append(str(err_msg))
                if err_type:
                    all_error_types.append(str(err_type))
                cap = evt.get("capability", "")
                src = evt.get("source", "")
                if cap:
                    evidence.append(
                        f"TaskFailed at capability='{cap}' "
                        f"(source={src}): {str(err_msg)[:200]}"
                    )
                elif err_msg:
                    evidence.append(
                        f"TaskFailed (source={src}): {str(err_msg)[:200]}"
                    )

        record_error = record.get("error", "")
        if record_error and record_error not in all_errors:
            all_errors.append(str(record_error))
            evidence.append(f"Record-level error: {str(record_error)[:200]}")

        # Multi-signal analysis
        latency = float(record.get("total_latency_ms", 0) or 0)
        if latency > 300_000:
            evidence.append(
                f"Execution took {latency:.0f}ms ({latency/1000:.0f}s) - "
                f"abnormally long, suggesting timeout or hung operation"
            )

        tokens = int(record.get("total_tokens", 0) or 0)
        runtime_id = str(record.get("runtime_id", "") or "")
        context_limit, matched_key = _resolve_context_limit(runtime_id)
        token_ratio = tokens / max(context_limit, 1)
        if token_ratio >= _CONTEXT_OVERFLOW_THRESHOLD:
            evidence.append(
                f"Consumed {tokens} tokens ({token_ratio:.0%} of "
                f"{matched_key} context window of {context_limit:,}) - "
                f"context pressure likely"
            )
        elif token_ratio >= 0.5:
            evidence.append(
                f"Consumed {tokens} tokens ({token_ratio:.0%} of "
                f"{matched_key} context window)"
            )

        multi_attempt_tasks = {
            tid: count for tid, count in task_attempts.items() if count >= 2
        }
        if multi_attempt_tasks:
            evidence.append(
                f"{len(multi_attempt_tasks)} task(s) retried multiple times: "
                f"{list(multi_attempt_tasks.keys())[:3]} - possible reasoning loop"
            )

        unique_errors = list({_extract_failure_pattern(e) for e in all_errors})
        if len(unique_errors) >= 2:
            evidence.append(
                f"{len(unique_errors)} distinct error patterns across "
                f"{len(failed_events)} failed events - agent tried different "
                f"approaches and none worked (reasoning issue, not isolated tool bug)"
            )

        # Classify
        combined_error = " | ".join(all_errors[:3])
        combined_etype = " | ".join(all_error_types[:3])
        cap_name = str(record.get("manifest_name", "") or "")
        classification = self.classify_failure(
            error_type=combined_etype,
            error_message=combined_error,
            capability=cap_name,
            latency=latency,
            tokens=tokens,
            runtime_id=runtime_id,
        )

        # Similar past failures
        similar_experiences = self._find_similar_failures(
            agent_id=str(record.get("agent_id", "") or ""),
            error_text=combined_error,
            failure_type=classification["type"],
        )

        fix_suggestion = self._build_fix_suggestion(
            root_cause_type=classification["type"],
            record=record,
            all_errors=all_errors,
            tokens=tokens,
            context_limit=context_limit,
            runtime_id=runtime_id,
            failed_events=failed_events,
            similar_experiences=similar_experiences,
        )

        improvement = self._estimate_improvement(
            classification["type"], similar_experiences
        )

        error_summary = (all_errors[0] if all_errors else "unknown error")[:120]
        verdict = (
            f"Execution {trace_id} failed due to "
            f"{classification['type'].replace('_', ' ')}: {error_summary}"
        )

        return {
            "verdict": verdict,
            "confidence": classification["confidence"],
            "root_cause_type": classification["type"],
            "evidence": evidence if evidence else ["No detailed event evidence available"],
            "fix_suggestion": fix_suggestion,
            "estimated_success_improvement": improvement,
            "similar_past_failures": [
                e["experience_id"] for e in similar_experiences
            ],
        }

    def _diagnose_agent_aggregate(self, agent_id: str) -> dict[str, Any]:
        """Aggregate diagnosis across all recent failures for an agent."""
        conn = self._conn()
        cutoff = _cutoff_iso(30)
        rows = conn.execute(
            """SELECT * FROM execution_records
               WHERE agent_id = ?
                 AND status IN ('failure', 'partial')
                 AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT 50""",
            (agent_id, cutoff),
        ).fetchall()

        records = [dict(r) for r in rows]

        if not records:
            return {
                "verdict": (
                    f"Agent '{agent_id}' has no recent failures "
                    f"in the last 30 days. No diagnosis needed."
                ),
                "confidence": 1.0,
                "root_cause_type": "unknown",
                "evidence": ["No failures found in the 30-day window."],
                "fix_suggestion": (
                    "Agent is performing well. Continue monitoring with: "
                    "intent-os doctor"
                ),
                "estimated_success_improvement": "0%",
                "similar_past_failures": [],
            }

        classifications: list[dict[str, Any]] = []
        for rec in records:
            c = self.classify_failure(
                error_type="",
                error_message=str(rec.get("error", "") or ""),
                capability=str(rec.get("manifest_name", "") or ""),
                latency=float(rec.get("total_latency_ms", 0) or 0),
                tokens=int(rec.get("total_tokens", 0) or 0),
                runtime_id=str(rec.get("runtime_id", "") or ""),
            )
            classifications.append(c)

        type_counts: Counter[str] = Counter()
        type_examples: dict[str, list[str]] = defaultdict(list)
        for ci, c in enumerate(classifications):
            t = c["type"]
            type_counts[t] += 1
            if len(type_examples[t]) < 3:
                rec = records[ci]
                err = str(rec.get("error", "") or "")[:120]
                if err:
                    type_examples[t].append(err)

        dominant_type, dominant_count = type_counts.most_common(1)[0]
        total = len(records)

        evidence: list[str] = [
            f"Analyzed {total} recent failures for agent '{agent_id}'",
        ]
        for ftype, count in type_counts.most_common(5):
            pct = count / total * 100
            evidence.append(
                f"{ftype.replace('_', ' ').title()}: {count}/{total} ({pct:.0f}%)"
            )
            for example in type_examples[ftype][:2]:
                evidence.append(f"  Example: {example}")

        avg_tokens = sum(
            int(r.get("total_tokens", 0) or 0) for r in records
        ) / max(total, 1)
        avg_latency = sum(
            float(r.get("total_latency_ms", 0) or 0) for r in records
        ) / max(total, 1)

        if avg_tokens > 100_000:
            evidence.append(
                f"Average token consumption is {avg_tokens:.0f} across failures - "
                f"systemically high, consider model with larger context"
            )
        if avg_latency > 120_000:
            evidence.append(
                f"Average latency is {avg_latency:.0f}ms "
                f"({avg_latency/1000:.0f}s) - systemically slow"
            )

        combined_errors = " | ".join([
            str(r.get("error", "") or "")[:200] for r in records[:5]
        ])
        similar_experiences = self._find_similar_failures(
            agent_id=agent_id,
            error_text=combined_errors,
            failure_type=dominant_type,
        )

        runtime_ids = list({
            str(r.get("runtime_id", "") or "")
            for r in records if r.get("runtime_id")
        })
        model_note = f" on {runtime_ids[0]}" if runtime_ids else ""

        verdict = (
            f"Agent '{agent_id}' had {total} failures in 30 days{model_note}. "
            f"Dominant root cause: {dominant_type.replace('_', ' ')} "
            f"({dominant_count}/{total}, {dominant_count/total*100:.0f}%). "
            f"Most common error: {(records[0].get('error') or 'none')[:100]}"
        )

        fix_suggestion = self._build_aggregate_fix_suggestion(
            dominant_type=dominant_type,
            records=records,
            type_counts=type_counts,
            total=total,
            avg_tokens=avg_tokens,
            avg_latency=avg_latency,
            similar_experiences=similar_experiences,
        )

        improvement = self._estimate_improvement(
            dominant_type, similar_experiences
        )

        return {
            "verdict": verdict,
            "confidence": _safe_round(dominant_count / total, 2),
            "root_cause_type": dominant_type,
            "evidence": evidence,
            "fix_suggestion": fix_suggestion,
            "estimated_success_improvement": improvement,
            "similar_past_failures": [
                e["experience_id"] for e in similar_experiences
            ],
        }

    def _diagnose_latest(self) -> dict[str, Any]:
        """Diagnose the most recent failure across all agents."""
        conn = self._conn()
        row = conn.execute(
            """SELECT trace_id FROM execution_records
               WHERE status IN ('failure', 'partial')
               ORDER BY created_at DESC
               LIMIT 1"""
        ).fetchone()

        if row is None:
            return {
                "verdict": "No failed executions found in the store.",
                "confidence": 1.0,
                "root_cause_type": "unknown",
                "evidence": ["Event store contains no failed/partial records."],
                "fix_suggestion": (
                    "No failures to diagnose. Run an agent first: "
                    "intent-os run <capability>"
                ),
                "estimated_success_improvement": "0%",
                "similar_past_failures": [],
            }

        return self._diagnose_single(row["trace_id"])

    # ============================================================
    # _find_similar_failures
    # ============================================================

    def _find_similar_failures(
        self,
        agent_id: str,
        error_text: str,
        failure_type: str,
    ) -> list[dict[str, Any]]:
        """Search the Experience Store for matching failure_pattern experiences."""
        results: list[dict[str, Any]] = []

        if agent_id:
            by_agent = self._exp_store.list(
                agent_id=agent_id,
                type="failure_pattern",
                limit=_MAX_SIMILAR_FAILURES,
            )
            results.extend(by_agent)

        if error_text:
            by_keyword = self._exp_store.query_by_task(
                goal=error_text[:200],
                limit=_MAX_SIMILAR_FAILURES,
            )
            for exp in by_keyword:
                if exp.get("type") == "failure_pattern" and exp not in results:
                    results.append(exp)

        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for exp in results:
            eid = exp.get("experience_id", "")
            if eid and eid not in seen:
                seen.add(eid)
                unique.append(exp)
                if len(unique) >= _MAX_SIMILAR_FAILURES:
                    break

        return unique

    # ============================================================
    # _build_fix_suggestion (single execution)
    # ============================================================

    def _build_fix_suggestion(
        self,
        root_cause_type: str,
        record: dict[str, Any],
        all_errors: list[str],
        tokens: int,
        context_limit: int,
        runtime_id: str,
        failed_events: list[dict[str, Any]],
        similar_experiences: list[dict[str, Any]],
    ) -> str:
        """Build a specific, actionable fix suggestion."""

        for exp in similar_experiences:
            rec = exp.get("recommendation", "")
            if rec and exp.get("success_rate_when_applied", 0) > 0.5:
                return (
                    f"[From past experience '{exp['experience_id']}'] {rec}"
                )

        manifest_name = str(
            record.get("manifest_name", "<capability>") or "<capability>"
        )
        first_error = all_errors[0] if all_errors else "unknown error"

        if root_cause_type == "tool_failure":
            failed_caps = [
                evt.get("capability", "")
                for evt in failed_events if evt.get("capability")
            ]
            cap_detail = failed_caps[0] if failed_caps else manifest_name
            return (
                f"The tool or capability '{cap_detail}' failed with: "
                f"{first_error[:150]}. Check that all required API credentials "
                f"are set (run: env | grep -E 'API_KEY|TOKEN|SECRET'). "
                f"Verify the tool implementation by running it in isolation: "
                f"intent-os run {manifest_name} --dry-run. If the error persists, "
                f"check the tool adapter logs at ~/.intent-os/logs/adapter.log "
                f"for stack traces."
            )

        elif root_cause_type == "context_overflow":
            token_ratio = tokens / max(context_limit, 1)
            upgrade = _upgrade_suggestion(runtime_id)
            if upgrade:
                model_change = (
                    f"Switch your model from '{runtime_id or 'current'}' to "
                    f"'{upgrade['suggestion']}' ({upgrade['limit']} context window): "
                    f"{upgrade['how']}"
                )
            else:
                model_change = (
                    f"Switch to a model with a larger context window. "
                    f"Current: {runtime_id or 'unknown'} ({context_limit:,} tokens). "
                    f"Used: {tokens:,} tokens ({token_ratio:.0%})."
                )
            return (
                f"Context overflow: {tokens:,} tokens used against a "
                f"{context_limit:,} limit ({token_ratio:.0%}) on model "
                f"'{runtime_id or 'unknown'}'. {model_change}. "
                f"Alternatively, reduce input size by splitting the task - "
                f"use the 'chunk_size' parameter in {manifest_name} manifest "
                f"to process data in batches."
            )

        elif root_cause_type == "reasoning_error":
            distinct = len({_extract_failure_pattern(e) for e in all_errors})
            return (
                f"The model attempted {distinct} different approaches but all "
                f"failed. This suggests the task '{manifest_name}' is too complex "
                f"or ambiguous for the current model. Add a 'max_retries' parameter "
                f"to your manifest (currently likely unset) and set it to 2 to "
                f"prevent infinite loops. Add a fallback task in your workflow: "
                f"edit the manifest YAML for {manifest_name} and add an "
                f"'on_failure: fallback_task' step. If using a smaller model, "
                f"upgrade to a reasoning-focused model like 'claude-opus-4-8' "
                f"or 'o3' for complex multi-step tasks."
            )

        elif root_cause_type == "model_hallucination":
            return (
                f"The model '{runtime_id or 'current'}' appears to have "
                f"hallucinated a non-existent tool, function, or resource: "
                f"{first_error[:150]}. Verify that all tool names in your "
                f"manifest match the registered adapters. Run "
                f"'intent-os adapter list' to see available tools. If the "
                f"tool name is correct, the model may need a lower temperature "
                f"setting - add 'temperature: 0.3' to your manifest's "
                f"requirements section to reduce hallucination risk."
            )

        elif root_cause_type == "rate_limit":
            return (
                f"Rate limit hit: {first_error[:150]}. Increase the "
                f"'retry_delay_ms' parameter in your manifest to at least "
                f"2000ms (2 seconds) and set 'max_retries' to 5. If you are "
                f"on a free or tiered API plan, check your usage limits at "
                f"your provider's dashboard and consider upgrading to a higher "
                f"tier. For OpenAI: https://platform.openai.com/account/limits. "
                f"For Anthropic: https://console.anthropic.com/settings/limits."
            )

        elif root_cause_type == "permission_denied":
            return (
                f"Permission denied: {first_error[:150]}. Check file permissions "
                f"and API key validity. Verify your API key is set and has the "
                f"required scopes: echo $ANTHROPIC_API_KEY (or $OPENAI_API_KEY). "
                f"If the agent needs filesystem access, grant it via: "
                f"intent-os policy grant <agent_id> --resource filesystem "
                f"--path <path>. Check the team policy for this agent: "
                f"intent-os policy show --agent {record.get('agent_id', '<id>')}."
            )

        elif root_cause_type == "timeout":
            current_latency = float(
                record.get("total_latency_ms", 30000) or 30000
            )
            suggested = max(current_latency * 2, 60000)
            return (
                f"Timeout detected: {first_error[:150]}. Latency was "
                f"{current_latency:.0f}ms. Increase the 'timeout_ms' parameter "
                f"in your manifest to at least {suggested:.0f}ms. Also check "
                f"network connectivity: ping your API endpoint to verify latency. "
                f"If using a proxy, ensure the proxy timeout is longer than the "
                f"manifest timeout."
            )

        else:
            return (
                f"Unable to classify the failure automatically. The error was: "
                f"{first_error[:200]}. Run 'intent-os doctor' for a full health "
                f"report, or inspect the full trace with: intent-os inspect "
                f"{record.get('trace_id', 'latest')}. Check the raw event log at "
                f"~/.intent-os/logs/ for detailed diagnostics."
            )

    # ============================================================
    # _build_aggregate_fix_suggestion
    # ============================================================

    def _build_aggregate_fix_suggestion(
        self,
        dominant_type: str,
        records: list[dict[str, Any]],
        type_counts: Counter[str],
        total: int,
        avg_tokens: float,
        avg_latency: float,
        similar_experiences: list[dict[str, Any]],
    ) -> str:
        """Build an aggregate fix suggestion for an agent's failure profile."""

        for exp in similar_experiences:
            rec = exp.get("recommendation", "")
            if rec and exp.get("success_rate_when_applied", 0) > 0.5:
                return (
                    f"[From past experience '{exp['experience_id']}'] {rec}. "
                    f"Additionally, address the dominant failure type below."
                )

        runtime_ids = list({
            str(r.get("runtime_id", "") or "")
            for r in records if r.get("runtime_id")
        })
        current_model = runtime_ids[0] if runtime_ids else "unknown"
        manifest_names = list({
            str(r.get("manifest_name", "") or "")
            for r in records if r.get("manifest_name")
        })
        manifest_note = f" for '{manifest_names[0]}'" if manifest_names else ""
        dc = type_counts.get(dominant_type, 0)

        if dominant_type == "tool_failure":
            return (
                f"Agent has {dc}/{total} tool failures{manifest_note}. "
                f"Check that all tools referenced by this agent are properly "
                f"registered. Run: intent-os adapter list --agent <agent_id>. "
                f"Verify API keys are set: env | grep API_KEY. Test each tool "
                f"in isolation with: intent-os run <capability> --dry-run. "
                f"Consider adding a pre-flight tool-health check step to your "
                f"workflow."
            )

        elif dominant_type == "context_overflow":
            upgrade = _upgrade_suggestion(current_model)
            model_change = (
                f"Switch from '{current_model}' to '{upgrade['suggestion']}' "
                f"({upgrade['limit']}): {upgrade['how']}"
            ) if upgrade else (
                f"Switch to a larger-context model (current: {current_model})"
            )
            return (
                f"Agent has {dc}/{total} context overflow failures{manifest_note} "
                f"(avg {avg_tokens:.0f} tokens/execution). {model_change}. "
                f"Also add input-size guards to your manifest with "
                f"'max_input_chars' parameter to reject oversized requests "
                f"before execution."
            )

        elif dominant_type == "reasoning_error":
            return (
                f"Agent has {dc}/{total} reasoning errors{manifest_note}. "
                f"The tasks may be too complex or ambiguous for the current "
                f"model '{current_model}'. Upgrade to a reasoning-optimized "
                f"model: set runtime_id to 'claude-opus-4-8' or 'o3' in your "
                f"manifest. Add 'max_retries: 2' to prevent costly retry loops. "
                f"Add a 'on_failure: notify' step to alert you when the agent "
                f"gets stuck rather than silently retrying."
            )

        elif dominant_type == "model_hallucination":
            return (
                f"Agent has {dc}/{total} hallucination failures{manifest_note} "
                f"on model '{current_model}'. Add 'temperature: 0.2' and "
                f"'top_p: 0.9' to your manifest requirements to reduce creative "
                f"output. Ensure all tool names in the manifest exactly match "
                f"registered adapters (run: intent-os adapter list). Consider "
                f"switching to a more reliable model: set runtime_id to "
                f"'claude-sonnet-4' which has lower hallucination rates for "
                f"tool use."
            )

        elif dominant_type == "rate_limit":
            return (
                f"Agent has {dc}/{total} rate-limit failures{manifest_note}. "
                f"Increase 'retry_delay_ms' to 5000ms and 'max_retries' to 3 "
                f"in your manifest. Add exponential backoff: set "
                f"'backoff_multiplier: 2.0' in manifest requirements. Check "
                f"your API plan limits and consider upgrading if you regularly "
                f"hit quotas."
            )

        elif dominant_type == "permission_denied":
            return (
                f"Agent has {dc}/{total} permission denials{manifest_note}. "
                f"Audit and fix: intent-os policy audit --agent <agent_id>. "
                f"Grant missing permissions: intent-os policy grant <agent_id> "
                f"--resource <name>. Verify API keys have correct scopes at "
                f"your provider's console."
            )

        elif dominant_type == "timeout":
            suggested = max(avg_latency * 2, 120_000)
            return (
                f"Agent has {dc}/{total} timeout failures{manifest_note} "
                f"(avg latency {avg_latency:.0f}ms). Increase 'timeout_ms' "
                f"to {suggested:.0f}ms in your manifest. Check network "
                f"health: ping your API endpoint. If using a proxy "
                f"(intent-os proxy), ensure its timeout exceeds your manifest "
                f"timeout. Consider adding a 'health_check' step before "
                f"long-running tasks."
            )

        else:
            return (
                f"Agent has {total} unclassified failures{manifest_note}. "
                f"Run 'intent-os doctor' for detailed per-execution diagnosis. "
                f"Review raw logs at ~/.intent-os/logs/ for patterns. Consider "
                f"running 'intent-os inspect latest --verbose' to see the full "
                f"event trace for the most recent failure."
            )

    # ============================================================
    # _estimate_improvement
    # ============================================================

    @staticmethod
    def _estimate_improvement(
        root_cause_type: str,
        similar_experiences: list[dict[str, Any]],
    ) -> str:
        """Estimate success-rate improvement if the fix is applied."""
        for exp in similar_experiences:
            rate = exp.get("success_rate_when_applied", 0)
            if rate > 0.5:
                return f"{rate * 100:.0f}% (based on past fix outcomes)"

        estimates = {
            "tool_failure": "40-60%",
            "context_overflow": "70-90%",
            "reasoning_error": "30-50%",
            "model_hallucination": "50-70%",
            "rate_limit": "80-95%",
            "permission_denied": "90-100%",
            "timeout": "50-80%",
            "unknown": "10-30%",
        }
        return estimates.get(root_cause_type, "10-30%")

    # ============================================================
    # get_failure_taxonomy
    # ============================================================

    def get_failure_taxonomy(
        self,
        agent_id: str | None = None,
        since_days: int = 30,
    ) -> dict[str, Any]:
        """Return aggregated failure statistics for an agent or globally.

        Args:
            agent_id: Optional agent to scope to. None = all agents.
            since_days: Look-back window in days (default 30).

        Returns:
            Dict with: total_executions, total_failures, failure_rate,
            by_type, trend, most_common_fix.
        """
        conn = self._conn()
        cutoff = _cutoff_iso(since_days)

        agent_filter = "AND agent_id = ?" if agent_id else ""
        params_fail: list[Any] = [cutoff]
        if agent_id:
            params_fail.append(agent_id)

        total_row = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE created_at >= ? {agent_filter}""",
            params_fail,
        ).fetchone()
        total_executions = total_row["total"] if total_row else 0

        fail_row = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE status IN ('failure', 'partial')
                  AND created_at >= ? {agent_filter}""",
            params_fail,
        ).fetchone()
        total_failures = fail_row["total"] if fail_row else 0

        if total_executions == 0:
            return {
                "total_executions": 0,
                "total_failures": 0,
                "failure_rate": 0.0,
                "by_type": {},
                "trend": "insufficient_data",
                "most_common_fix": (
                    "No execution data available. Run an agent first: "
                    "intent-os run <capability>"
                ),
            }

        failure_rate = _safe_round(total_failures / max(total_executions, 1), 4)

        params_records: list[Any] = [cutoff]
        if agent_id:
            params_records.append(agent_id)

        fail_records = conn.execute(
            f"""SELECT error, total_latency_ms, total_tokens,
                       runtime_id, manifest_name
                FROM execution_records
                WHERE status IN ('failure', 'partial')
                  AND created_at >= ? {agent_filter}
                ORDER BY created_at DESC""",
            params_records,
        ).fetchall()

        by_type: Counter[str] = Counter()
        for row in fail_records:
            c = self.classify_failure(
                error_type="",
                error_message=str(row["error"] or ""),
                capability=str(row["manifest_name"] or ""),
                latency=float(row["total_latency_ms"] or 0),
                tokens=int(row["total_tokens"] or 0),
                runtime_id=str(row["runtime_id"] or ""),
            )
            by_type[c["type"]] += 1

        trend = self._compute_trend(
            conn=conn,
            cutoff=cutoff,
            since_days=since_days,
            agent_id=agent_id,
            agent_filter=agent_filter,
        )

        most_common_fix = self._most_common_fix(
            by_type=by_type,
            total_failures=total_failures,
            fail_records=fail_records,
            agent_id=agent_id,
        )

        return {
            "total_executions": total_executions,
            "total_failures": total_failures,
            "failure_rate": failure_rate,
            "by_type": dict(by_type.most_common(_MAX_TAXONOMY_TYPES)),
            "trend": trend,
            "most_common_fix": most_common_fix,
        }

    # ============================================================
    # _compute_trend
    # ============================================================

    @staticmethod
    def _compute_trend(
        conn: Any,
        cutoff: str,
        since_days: int,
        agent_id: str | None,
        agent_filter: str,
    ) -> str:
        """Compare failure rates between first and second halves of window."""
        if since_days < 2:
            return "insufficient_data"

        half_days = since_days // 2
        midpoint = (
            datetime.now(timezone.utc) - timedelta(days=half_days)
        ).isoformat()

        params: list[Any] = [cutoff, midpoint]
        if agent_id:
            params = [cutoff, midpoint, agent_id, agent_id]

        first_total = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE created_at >= ? AND created_at < ? {agent_filter}""",
            params,
        ).fetchone()["total"] or 0

        first_fails = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE status IN ('failure', 'partial')
                  AND created_at >= ? AND created_at < ? {agent_filter}""",
            params,
        ).fetchone()["total"] or 0

        params2: list[Any] = [midpoint]
        if agent_id:
            params2.append(agent_id)

        second_total = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE created_at >= ? {agent_filter}""",
            params2,
        ).fetchone()["total"] or 0

        second_fails = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM execution_records
                WHERE status IN ('failure', 'partial')
                  AND created_at >= ? {agent_filter}""",
            params2,
        ).fetchone()["total"] or 0

        if (
            first_total < _MIN_EXECUTIONS_FOR_TREND
            or second_total < _MIN_EXECUTIONS_FOR_TREND
        ):
            if first_total + second_total < _MIN_EXECUTIONS_FOR_TREND:
                return "insufficient_data"

        first_rate = first_fails / max(first_total, 1)
        second_rate = second_fails / max(second_total, 1)

        if second_rate == 0 and first_rate == 0:
            return "stable"

        if first_rate == 0:
            return "worsening" if second_rate > 0.05 else "stable"

        relative_change = (second_rate - first_rate) / first_rate

        if relative_change <= -0.20:
            return "improving"
        elif relative_change >= 0.20:
            return "worsening"
        else:
            return "stable"

    # ============================================================
    # _most_common_fix
    # ============================================================

    def _most_common_fix(
        self,
        by_type: Counter[str],
        total_failures: int,
        fail_records: list[Any],
        agent_id: str | None,
    ) -> str:
        """Generate the single most actionable recommendation."""
        if not by_type or total_failures == 0:
            return "No failures to fix."

        dominant_type, dominant_count = by_type.most_common(1)[0]
        pct = dominant_count / total_failures * 100

        runtime_ids = list({
            str(r["runtime_id"] or "")
            for r in fail_records if r.get("runtime_id")
        })
        model = runtime_ids[0] if runtime_ids else "unknown"
        manifest_names = list({
            str(r["manifest_name"] or "")
            for r in fail_records if r.get("manifest_name")
        })

        prefix = (
            f"{dominant_count}/{total_failures} failures ({pct:.0f}%) are "
            f"'{dominant_type.replace('_', ' ')}'"
        )
        if agent_id:
            prefix += f" for agent '{agent_id}'"

        if dominant_type == "rate_limit":
            return (
                f"{prefix}. Fix: Increase 'retry_delay_ms' to 5000ms and "
                f"'max_retries' to 3 in your capability manifest. Set "
                f"'backoff_multiplier: 2.0' for exponential backoff. Check "
                f"your API plan limits at your provider's dashboard."
            )

        elif dominant_type == "context_overflow":
            upgrade = _upgrade_suggestion(model)
            if upgrade:
                model_advice = (
                    f"Switch runtime_id to '{upgrade['suggestion']}' "
                    f"({upgrade['limit']}). How: {upgrade['how']}"
                )
            else:
                model_advice = f"Switch to a model with larger context than '{model}'"
            return (
                f"{prefix}. Fix: {model_advice}. Alternatively, add "
                f"'max_input_chars' or 'chunk_size' to your manifest to "
                f"split large inputs before they hit the model."
            )

        elif dominant_type == "tool_failure":
            cap_note = f" for '{manifest_names[0]}'" if manifest_names else ""
            return (
                f"{prefix}{cap_note}. Fix: Verify all tool adapters are "
                f"registered (intent-os adapter list). Check API credentials "
                f"are valid (env | grep API_KEY). Test each failing tool with "
                f"intent-os run <capability> --dry-run. Check adapter logs at "
                f"~/.intent-os/logs/adapter.log."
            )

        elif dominant_type == "reasoning_error":
            return (
                f"{prefix}. Fix: Upgrade to a reasoning-optimized model: set "
                f"runtime_id to 'claude-opus-4-8' or 'o3' in your manifest. "
                f"Add 'max_retries: 2' to prevent costly loops. Add a fallback "
                f"task in your workflow for graceful degradation."
            )

        elif dominant_type == "model_hallucination":
            return (
                f"{prefix}. Fix: Lower temperature to 0.2 by adding "
                f"'temperature: 0.2' to manifest requirements. Verify tool "
                f"names match registered adapters exactly (intent-os adapter "
                f"list). Consider switching to 'claude-sonnet-4' which has "
                f"lower hallucination rates for tool use."
            )

        elif dominant_type == "permission_denied":
            agent_clause = f" --agent {agent_id}" if agent_id else ""
            return (
                f"{prefix}. Fix: Run 'intent-os policy audit{agent_clause}' "
                f"to identify missing permissions. Grant access with: "
                f"intent-os policy grant <agent_id> --resource <name>. "
                f"Verify API key scopes at your provider's console."
            )

        elif dominant_type == "timeout":
            avg_lat = sum(
                float(r["total_latency_ms"] or 0) for r in fail_records
            ) / max(len(fail_records), 1)
            suggested_timeout = max(avg_lat * 2, 120_000)
            return (
                f"{prefix}. Fix: Increase 'timeout_ms' to at least "
                f"{suggested_timeout:.0f}ms in your manifest. Check network "
                f"connectivity to the API endpoint. If using a proxy, ensure "
                f"its timeout exceeds the manifest timeout."
            )

        else:
            return (
                f"{prefix}. Fix: Run 'intent-os doctor' for detailed diagnosis "
                f"of recent failures. Inspect the full trace with: "
                f"intent-os inspect latest --verbose."
            )
