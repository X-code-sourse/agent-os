"""
Intent OS — Context Retrieval (SPEC-0010 Layer 2+3 Retrieval)

Given an agent ID and a user query string, retrieves the most relevant
Capability + Experience entries using keyword matching.

No vector database — just structured field matching + keyword scoring.
Designed to be called from ``context_injector.build_injection_prompt()``
or directly from the CLI.

Usage::

    from core.context_retrieval import retrieve_context

    results = retrieve_context("agent_a82f91c3", "analyze Nvidia earnings")
    for r in results:
        print(f"[{r.relevance_score:.2f}] {r.source}: {r.content}")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_MIN_KEYWORD_LEN = 3
_DEFAULT_MAX_RESULTS = 5


@dataclass
class RetrievedContext:
    """A single context retrieval result.

    Attributes:
        source: ``"capability"`` or ``"experience"``.
        relevance_score: 0.0–1.0 relevance to the query.
        content: Human-readable summary of the matched context.
        confidence: Confidence/credibility of the source data (0.0–1.0).
        source_id: Capability name or experience ID.
    """
    source: str
    relevance_score: float
    content: str
    confidence: float = 0.0
    source_id: str = ""


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a query (words 3+ chars)."""
    words = re.findall(r"[a-zA-Z0-9_一-鿿]{3,}", text.lower())
    return [w for w in words if len(w) >= _MIN_KEYWORD_LEN]


def _keyword_overlap(query_keywords: list[str],
                     target_texts: list[str]) -> float:
    """Fraction of query keywords that appear in any of the target texts."""
    if not query_keywords:
        return 0.0
    target_lower = " ".join(t.lower() for t in target_texts)
    matches = sum(1 for kw in query_keywords if kw in target_lower)
    return matches / len(query_keywords)


def retrieve_context(
    agent_id: str,
    query: str,
    max_results: int = _DEFAULT_MAX_RESULTS,
    db_path: str | None = None,
) -> list[RetrievedContext]:
    """Retrieve the most relevant context for an agent given a query.

    Args:
        agent_id: The agent to search.
        query: The user's request text.
        max_results: Maximum number of results to return.
        db_path: Optional custom database path (for testing).

    Returns:
        A list of :class:`RetrievedContext` sorted by ``relevance_score``
        descending.  Empty list if nothing matches.
    """
    from core.capability_context import compute_capability_profile
    from core.experience_store import ExperienceStore

    keywords = _extract_keywords(query)
    results: list[RetrievedContext] = []

    if not keywords:
        # Empty query — return most recent experiences as fallback
        try:
            exp_store = ExperienceStore(db_path)
            exps = exp_store.list(agent_id=agent_id, limit=max_results)
            for exp in exps:
                obs = (exp.get("observation") or "").strip()[:120]
                etype = exp.get("type", "unknown")
                if obs:
                    results.append(RetrievedContext(
                        source="experience",
                        relevance_score=0.5,
                        content=obs,
                        confidence=float(exp.get("confidence", 0.0)),
                        source_id=exp.get("experience_id", ""),
                    ))
        except Exception:
            pass
        return results

    # ── Match capabilities ──
    try:
        profiles = compute_capability_profile(agent_id, db_path=db_path)
        for p in profiles:
            targets = [p.name, p.label]
            targets.extend(pt.task_type for pt in p.proven_patterns)
            overlap = _keyword_overlap(keywords, targets)
            if overlap > 0:
                level_tag = {"expert": "EXP", "proficient": "PRF", "practitioner": "PRA"}
                tag = level_tag.get(p.level, "?")
                results.append(RetrievedContext(
                    source="capability",
                    relevance_score=min(1.0, overlap
                                        * (1 + 0.1 * min(p.total_tasks, 100) / 100)),
                    content=f"{p.label}: {p.success_rate:.0%} success ({p.total_tasks} tasks, {tag})",
                    confidence=p.success_rate,
                    source_id=p.name,
                ))
    except Exception:
        pass

    # ── Match experiences ──
    try:
        exp_store = ExperienceStore(db_path)
        exps = exp_store.list(agent_id=agent_id, limit=200)
        for exp in exps:
            obs = (exp.get("observation") or "").strip()
            sit = exp.get("structured_situation") or ""
            trig = exp.get("structured_trigger") or ""
            conf = float(exp.get("confidence", 0.0))
            usage = int(exp.get("usage_count", 0))

            targets = [obs, sit, trig]
            overlap = _keyword_overlap(keywords, targets)
            if overlap > 0:
                score = min(1.0, overlap * (1 + 0.2 * conf))
                content = (obs or sit or "")[:150]
                results.append(RetrievedContext(
                    source="experience",
                    relevance_score=score,
                    content=content,
                    confidence=conf,
                    source_id=exp.get("experience_id", ""),
                ))
    except Exception:
        pass

    # ── Match environment ──
    env_keywords = ["adapter", "runtime", "platform", "ollama", "openai", "anthropic",
                    "tool", "environment", "where", "running"]
    if any(kw in keywords for kw in env_keywords):
        try:
            from core.environment_context import detect_environment, format_environment
            env = detect_environment()
            results.append(RetrievedContext(
                source="environment",
                relevance_score=0.6,
                content=f"Runtime: {env.runtime_version} | Adapters: {', '.join(env.available_adapters)}",
                confidence=1.0,
                source_id="environment",
            ))
        except Exception:
            pass

    # ── Match relationships ──
    rel_keywords = ["team", "teammate", "collaborate", "who", "partner", "member"]
    if any(kw in keywords for kw in rel_keywords):
        try:
            from core.relationship_context import compute_relationships
            rel = compute_relationships(agent_id)
            for t in rel.teams:
                results.append(RetrievedContext(
                    source="relationship",
                    relevance_score=0.7,
                    content=f"Team {t.name}: {t.member_count} members",
                    confidence=1.0,
                    source_id=t.team_id,
                ))
        except Exception:
            pass

    # ── Sort and limit ──
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    return results[:max_results]


def format_retrieved_context(results: list[RetrievedContext],
                             max_results: int = _DEFAULT_MAX_RESULTS) -> str | None:
    """Format retrieved context into a compact prompt injection string.

    Returns ``None`` if the results list is empty.
    """
    if not results:
        return None

    lines: list[str] = []
    cap_lines: list[str] = []
    exp_lines: list[str] = []

    for r in results[:max_results]:
        if r.source == "capability":
            cap_lines.append(f"  {r.content}")
        elif r.source == "experience":
            exp_lines.append(f"  {r.content}")

    if cap_lines:
        lines.append("Relevant capabilities:")
        lines.extend(cap_lines)
    if exp_lines:
        if cap_lines:
            lines.append("")
        lines.append("Relevant experience:")
        lines.extend(exp_lines)

    return "\n".join(lines) if lines else None
