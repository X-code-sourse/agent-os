"""
Intent OS — Workflow Planner (Phase 2: Data-Driven)

The Planner converts a user goal into an executable WorkflowDAG.

It implements a data-driven planner:
  - Predefined workflow templates for common task patterns
  - Goal matching: parse a goal → find best template → instantiate
  - Multi-plan enumeration with cost estimates via CostModel
  - Analytics-driven template/capability ranking based on historical data
  - Produces a validated WorkflowSpec ready for execution

Phase 3+ evolution:
  Multi-armed bandit exploration → Probabilistic query optimizer
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from core.models import CapabilityManifest
from core.registry import CapabilityRegistry
from core.workflow import (
    ExecutionSemantics,
    FailurePolicy,
    FailurePropagation,
    ParallelPolicy,
    ParallelStrategy,
    RetryPolicy,
    RetryStrategy,
    TimeoutPolicy,
    WorkflowDAG,
    WorkflowEdge,
    WorkflowSpec,
    WorkflowTask,
    WorkflowValidationError,
)

from core.cost_model import CostModel, CostEstimate, MultiPlanResult


# ──────────────────────────────────────────────
# Workflow Template
# ──────────────────────────────────────────────

@dataclass
class TemplateTask:
    """A task placeholder in a workflow template."""
    id: str
    capability_pattern: str  # Glob/regex for capability name matching
    description: str | None = None
    input_template: dict[str, str] = field(default_factory=dict)
    # input_template values can contain {goal.field} or {task_id.output} references


@dataclass
class TemplateEdge:
    """An edge placeholder in a workflow template."""
    from_task: str
    to_task: str
    data_mapping: dict[str, str] | None = None


@dataclass
class WorkflowTemplate:
    """
    A reusable workflow template.

    Templates define the shape of a workflow for a common task pattern.
    They are instantiated with concrete capability references and inputs
    at plan time.

    Example: a "research" template defines:
      search → analyze → report
    but doesn't specify which exact capabilities to use — that's
    resolved at plan time based on the registry and goal.
    """
    name: str
    description: str
    goal_pattern: str  # Regex to match against the user's goal
    tasks: list[TemplateTask]
    edges: list[TemplateEdge]
    semantics: ExecutionSemantics | None = None
    priority: int = 0  # Higher = preferred when multiple templates match


# ──────────────────────────────────────────────
# Built-in Templates
# ──────────────────────────────────────────────

BUILTIN_TEMPLATES: list[WorkflowTemplate] = [
    # Research workflow: search → analyze → report
    WorkflowTemplate(
        name="research",
        description="Research a topic: search, analyze, and generate a report",
        goal_pattern=r"(?i)(research|investigate|analyze|study|find|search)",
        tasks=[
            TemplateTask(
                id="search",
                capability_pattern="*search*",
                description="Search for information on the topic",
                input_template={"query": "{goal.topic}"},
            ),
            TemplateTask(
                id="analyze",
                capability_pattern="*analyze*",
                description="Analyze the search results",
                input_template={"text": "{search.results}"},
            ),
            TemplateTask(
                id="report",
                capability_pattern="*report*",
                description="Generate a report from the analysis",
                input_template={"analysis": "{analyze.result}"},
            ),
        ],
        edges=[
            TemplateEdge(from_task="search", to_task="analyze"),
            TemplateEdge(from_task="analyze", to_task="report"),
        ],
        semantics=ExecutionSemantics(
            retry=RetryPolicy(strategy=RetryStrategy.EXPONENTIAL, max_attempts=3),
            timeout=TimeoutPolicy(task_ms=60000, workflow_ms=300000),
            failure=FailurePolicy(
                propagation=FailurePropagation.DEFERRED,
                cancel_dependents=True,
                continue_independents=True,
            ),
            parallel=ParallelPolicy(
                strategy=ParallelStrategy.SEQUENTIAL,
            ),
        ),
    ),

    # Summarization: fetch → summarize
    WorkflowTemplate(
        name="summarize",
        description="Fetch content and summarize it",
        goal_pattern=r"(?i)(summarize|summary|extract|digest)",
        tasks=[
            TemplateTask(
                id="fetch",
                capability_pattern="*fetch*",
                description="Fetch the content to summarize",
                input_template={"url": "{goal.url}"},
            ),
            TemplateTask(
                id="summarize",
                capability_pattern="*summarize*",
                description="Summarize the fetched content",
                input_template={"text": "{fetch.content}"},
            ),
        ],
        edges=[
            TemplateEdge(from_task="fetch", to_task="summarize"),
        ],
        priority=1,
    ),

    # Analysis workflow: collect data → analyze → review
    WorkflowTemplate(
        name="analysis",
        description="Data collection, analysis, and review",
        goal_pattern=r"(?i)(analyze|analysis|evaluate|assess)",
        tasks=[
            TemplateTask(
                id="collect",
                capability_pattern="*search*",
                description="Collect data on the topic",
                input_template={"query": "{goal.topic}"},
            ),
            TemplateTask(
                id="analyze",
                capability_pattern="*analyze*",
                description="Analyze the collected data",
                input_template={"data": "{collect.results}"},
            ),
            TemplateTask(
                id="review",
                capability_pattern="*review*",
                description="Review the analysis",
                input_template={"analysis": "{analyze.result}"},
            ),
        ],
        edges=[
            TemplateEdge(from_task="collect", to_task="analyze"),
            TemplateEdge(from_task="analyze", to_task="review"),
        ],
    ),
]


# ──────────────────────────────────────────────
# Planner
# ──────────────────────────────────────────────

class PlanError(Exception):
    """Raised when workflow planning fails."""
    pass


class NoTemplateMatchError(PlanError):
    """Raised when no template matches the given goal."""
    pass


class NoCapabilityMatchError(PlanError):
    """Raised when a template task cannot be matched to registered capabilities."""
    pass


@dataclass
class PlanResult:
    """Result of the planning process."""
    workflow_dag: WorkflowDAG
    template_name: str
    goal: str
    matched_capabilities: dict[str, CapabilityManifest]
    warnings: list[str] = field(default_factory=list)


def _plans_are_identical(
    plan: PlanResult,
    existing: list[tuple[Any, CostEstimate]],
) -> bool:
    """Check if a plan is structurally identical to any already in the list.

    Compares task capabilities, edge structure, and execution semantics
    to detect true duplicates (same capability choices and semantics).
    """
    for existing_plan, _ in existing:
        s1 = plan.workflow_dag.spec
        s2 = existing_plan.workflow_dag.spec
        if (
            s1.semantics.parallel.strategy == s2.semantics.parallel.strategy
            and s1.semantics.retry == s2.semantics.retry
            and len(s1.tasks) == len(s2.tasks)
            and len(s1.edges) == len(s2.edges)
            and {t.capability for t in s1.tasks} == {t.capability for t in s2.tasks}
            and {(e.from_task, e.to_task) for e in s1.edges}
            == {(e.from_task, e.to_task) for e in s2.edges}
        ):
            return True
    return False


class WorkflowPlanner:
    """
    Template-based workflow planner.

    Given a user goal and a registry of available capabilities, the Planner:
      1. Matches the goal against known workflow templates
      2. Instantiates the best-matching template with concrete capabilities
      3. Resolves input bindings
      4. Produces a validated, ready-to-execute WorkflowDAG

    Phase 1: Template-based, deterministic.
    Phase 3+: Will evolve to enumerate multiple candidate plans and
              select the optimal one using cost estimation.
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        templates: list[WorkflowTemplate] | None = None,
        analytics: Any | None = None,
        cost_model: CostModel | None = None,
    ) -> None:
        self._registry = registry
        self._templates = templates or BUILTIN_TEMPLATES
        self._analytics = analytics
        self._cost_model = cost_model

    def set_registry(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def add_template(self, template: WorkflowTemplate) -> None:
        self._templates.append(template)

    def plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
    ) -> PlanResult:
        """
        Convert a user goal into an executable workflow plan.

        Args:
            goal: The user's goal description (e.g., "research NVIDIA stock").
            context: Optional context parameters (e.g., {"topic": "NVIDIA"}).

        Returns:
            PlanResult containing a validated WorkflowDAG.

        Raises:
            NoTemplateMatchError: If no template matches the goal.
            NoCapabilityMatchError: If capabilities cannot be resolved.
            PlanError: If instantiation fails.
        """
        context = context or {}

        # Step 1: Parse goal into structured fields
        goal_fields = self._parse_goal(goal)
        goal_fields.update(context)

        # Step 2: Find best matching template
        template = self._match_template(goal)
        if template is None:
            # Fall back to a single-capability passthrough
            template = self._create_passthrough_template(goal)

        # Step 3: Match template tasks to capabilities
        matched_caps: dict[str, CapabilityManifest] = {}
        warnings: list[str] = []

        for tmpl_task in template.tasks:
            if self._registry is None:
                # No registry available — create placeholder capability
                from core.models import (
                    CapabilityManifest, MetadataSpec, FieldSchema,
                    RequirementSpec, SecuritySpec,
                )
                warnings.append(f"No registry available; using placeholder for '{tmpl_task.id}'")
                matched_caps[tmpl_task.id] = CapabilityManifest(
                    metadata=MetadataSpec(
                        name=tmpl_task.id,
                        version="1.0.0",
                        description=tmpl_task.description or "",
                    ),
                    input_schema={"input": FieldSchema(type="string")},
                    output_schema={"output": FieldSchema(type="string")},
                    requirements=RequirementSpec(),
                    security=SecuritySpec(),
                )
                continue

            cap = self._resolve_capability(tmpl_task.capability_pattern)
            if cap is None:
                raise NoCapabilityMatchError(
                    f"No capability matches pattern '{tmpl_task.capability_pattern}' "
                    f"for task '{tmpl_task.id}'"
                )
            matched_caps[tmpl_task.id] = cap

        # Step 4: Instantiate tasks with concrete capabilities
        tasks: list[WorkflowTask] = []
        for tmpl_task in template.tasks:
            cap = matched_caps[tmpl_task.id]
            resolved_input = self._resolve_inputs(
                tmpl_task.input_template,
                goal_fields,
                {},
            )
            tasks.append(WorkflowTask(
                id=tmpl_task.id,
                capability=cap.id,
                input=resolved_input,
                description=tmpl_task.description,
            ))

        # Step 5: Instantiate edges
        edges: list[WorkflowEdge] = []
        for tmpl_edge in template.edges:
            edges.append(WorkflowEdge(
                from_task=tmpl_edge.from_task,
                to_task=tmpl_edge.to_task,
                data=tmpl_edge.data_mapping,
            ))

        # Step 6: Build the spec
        semantics = template.semantics or ExecutionSemantics.defaults()
        spec = WorkflowSpec(
            name=f"plan_{template.name}",
            version="1.0.0",
            tasks=tasks,
            edges=edges,
            semantics=semantics,
            description=f"Planned workflow for: {goal}",
            goal=goal,
        )

        # Step 7: Validate and build DAG
        try:
            dag = WorkflowDAG(spec)
        except WorkflowValidationError as exc:
            raise PlanError(f"Workflow validation failed: {exc}") from exc

        return PlanResult(
            workflow_dag=dag,
            template_name=template.name,
            goal=goal,
            matched_capabilities=matched_caps,
            warnings=warnings,
        )

    # ── Multi-Plan Enumeration ────────────────────────────────────

    def plan_candidates(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        top_n: int = 3,
    ) -> MultiPlanResult:
        """
        Enumerate multiple candidate plans for a goal, estimate costs,
        and return them sorted cheapest-first.

        Args:
            goal: The user's goal description.
            context: Optional context parameters.
            top_n: Maximum number of candidate plans to generate (default 3).

        Returns:
            MultiPlanResult with candidate plans, cost estimates,
            and recommended_index pointing to the cheapest plan.
        """
        context = context or {}
        goal_fields = self._parse_goal(goal)
        goal_fields.update(context)

        # Step 1: Get the best-matching template
        template = self._match_template(goal)
        if template is None:
            template = self._create_passthrough_template(goal)

        candidates: list[tuple[Any, CostEstimate]] = []

        # Variant 1: default template (as-is)
        try:
            plan_default = self.plan(goal, context)
            candidates.append((plan_default, self._estimate_plan(plan_default)))
        except PlanError:
            pass

        # Variant 2: cheaper capability alternatives
        if top_n >= 2:
            try:
                plan_cheap = self._build_plan_candidate(
                    template, goal, goal_fields,
                    prefer_cheap_caps=True,
                )
                cost_cheap = self._estimate_plan(plan_cheap)
                if not _plans_are_identical(plan_cheap, candidates):
                    candidates.append((plan_cheap, cost_cheap))
            except PlanError:
                pass

        # Variant 3: flip execution semantics (sequential -> parallel / parallel -> sequential)
        if top_n >= 3:
            try:
                plan_flip = self._build_plan_candidate(
                    template, goal, goal_fields,
                    force_parallel=True,
                )
                cost_flip = self._estimate_plan(plan_flip)
                if not _plans_are_identical(plan_flip, candidates):
                    candidates.append((plan_flip, cost_flip))
            except PlanError:
                pass

        # Sort by total estimated cost (cheapest first), break ties by latency
        candidates.sort(key=lambda x: (x[1].cost_usd, x[1].latency_ms))

        return MultiPlanResult(plans=candidates, recommended_index=0)

    @staticmethod
    def plan_summary(plan_result: PlanResult) -> dict[str, Any]:
        """
        Build a human-readable summary dict for CLI display.

        Args:
            plan_result: A PlanResult from plan() or plan_candidates().

        Returns:
            Dict with task_count, edge_count, template, goal, and the
            estimated cost / latency fields (set to 0 if no CostModel
            was used during planning).
        """
        task_count = len(plan_result.workflow_dag.spec.tasks)
        return {
            "template": plan_result.template_name,
            "goal": plan_result.goal,
            "task_count": task_count,
            "edge_count": len(plan_result.workflow_dag.spec.edges),
        }

    def _parse_goal(self, goal: str) -> dict[str, str]:
        """Parse a natural language goal into structured fields.

        Phase 1: Simple heuristic extraction.
        Phase 2+: LLM-based structured decomposition.
        """
        fields: dict[str, str] = {
            "goal": goal,
            "topic": goal,
        }

        # Try to extract topic after keywords
        patterns = [
            r"(?i)(?:research|analyze|investigate|about)\s+(.+?)(?:\.|$)",
            r"(?i)(?:find|search|study)\s+(.+?)(?:\.|$)",
            r"(?i)(?:summarize|summarise)\s+(.+?)(?:\.|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, goal)
            if match:
                topic = match.group(1).strip()
                if topic and len(topic) < 200:
                    fields["topic"] = topic
                    break

        return fields

    def _match_template(self, goal: str) -> WorkflowTemplate | None:
        """Find the best-matching template for the given goal.

        When analytics data is available, templates that have historically
        produced more successful executions are preferred.
        """
        perf: dict[str, int] = {}
        if self._analytics is not None:
            try:
                for entry in (self._analytics.get_capability_rankings() or []):
                    perf[entry.get("capability", "")] = entry.get("total_runs", 0)
            except Exception:
                pass  # Analytics data is optional — degrade gracefully

        candidates: list[tuple[WorkflowTemplate, int]] = []
        for template in self._templates:
            if re.search(template.goal_pattern, goal):
                score = template.priority * 10
                if len(template.goal_pattern) > 10:
                    score += 5
                score += min(perf.get(template.name, 0), 20)
                candidates.append((template, score))

        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]

    def _resolve_capability(
        self,
        pattern: str,
    ) -> CapabilityManifest | None:
        """Match a capability pattern against registered capabilities.

        When analytics data is available, prefers capabilities with
        higher historical success rates.
        """
        if self._registry is None:
            return None

        regex_pattern = re.escape(pattern).replace(r"\*", ".*")
        compiled = re.compile(f"^{regex_pattern}$", re.IGNORECASE)

        perf: dict[str, float] = {}
        if self._analytics is not None:
            try:
                for entry in (self._analytics.get_capability_rankings() or []):
                    n = entry.get("capability", "")
                    r = entry.get("success_rate", 0.5) or 0.0
                    perf[n] = r
            except Exception:
                pass  # Analytics data is optional — degrade gracefully

        matches: list[tuple[str, str, float]] = []
        capabilities = self._registry.list_capabilities()
        for cap_info in capabilities:
            if compiled.match(cap_info["name"]):
                score = perf.get(cap_info["name"], 0.5)
                matches.append((cap_info["name"], cap_info["version"], score))

        if not matches:
            return None
        matches.sort(key=lambda x: -x[2])
        return self._registry.get(matches[0][0], matches[0][1])

    def _resolve_cheapest_capability(
        self,
        pattern: str,
    ) -> CapabilityManifest | None:
        """
        Match a capability pattern and return the cheapest alternative.

        Uses the CostModel to estimate each matching capability's cost
        and returns the one with the lowest estimated cost.
        Falls back to _resolve_capability if no CostModel is available.
        """
        if self._cost_model is None:
            return self._resolve_capability(pattern)

        if self._registry is None:
            return None

        regex_pattern = re.escape(pattern).replace(r"\*", ".*")
        compiled = re.compile(f"^{regex_pattern}$", re.IGNORECASE)

        matches: list[tuple[str, str, float]] = []
        capabilities = self._registry.list_capabilities()
        for cap_info in capabilities:
            if compiled.match(cap_info["name"]):
                cap = self._registry.get(cap_info["name"], cap_info["version"])
                if cap is not None:
                    est = self._cost_model.estimate(cap, "openai", 1000)
                    matches.append((cap_info["name"], cap_info["version"], est.cost_usd))

        if not matches:
            return None
        matches.sort(key=lambda x: x[2])  # Sort by cost ascending
        return self._registry.get(matches[0][0], matches[0][1])

    def _resolve_inputs(
        self,
        input_template: dict[str, str],
        goal_fields: dict[str, str],
        task_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve template input bindings against goal fields.

        Replaces {goal.field} and {task_id.output} references
        with concrete values.
        """
        resolved: dict[str, Any] = {}
        for key, value_template in input_template.items():
            resolved_value = value_template
            # Replace {goal.xxx} references
            for field_name, field_value in goal_fields.items():
                resolved_value = resolved_value.replace(
                    f"{{goal.{field_name}}}", str(field_value)
                )
            # Replace {task_id.output} references (from prior tasks)
            # At plan time these will be placeholders; actual values
            # are filled at runtime by the Scheduler
            resolved[key] = resolved_value
        return resolved

    def _create_passthrough_template(self, goal: str) -> WorkflowTemplate:
        """Create a fallback template when no predefined template matches.

        This wraps the entire goal as a single capability invocation,
        allowing the system to fall back to direct execution.
        """
        return WorkflowTemplate(
            name="passthrough",
            description=f"Direct execution: {goal}",
            goal_pattern=".*",  # Match everything
            tasks=[
                TemplateTask(
                    id="execute",
                    capability_pattern="*",
                    description=str(goal),
                    input_template={"goal": "{goal.goal}"},
                ),
            ],
            edges=[],
            semantics=ExecutionSemantics.defaults(),
            priority=0,
        )

    # ── Candidate Building Helpers ──

    def _build_plan_candidate(
        self,
        template: WorkflowTemplate,
        goal: str,
        goal_fields: dict[str, str],
        prefer_cheap_caps: bool = False,
        force_parallel: bool = False,
    ) -> PlanResult:
        """
        Build a PlanResult from a template with optional variations.

        Args:
            template: The workflow template to instantiate.
            goal: Original goal string.
            goal_fields: Parsed goal fields.
            prefer_cheap_caps: If True, resolve cheapest capabilities.
            force_parallel: If True, toggle the execution semantics
                            (sequential -> parallel or vice versa).

        Returns:
            A validated PlanResult.
        """
        matched_caps: dict[str, CapabilityManifest] = {}
        warnings: list[str] = []

        for tmpl_task in template.tasks:
            if self._registry is None:
                from core.models import (
                    CapabilityManifest, MetadataSpec, FieldSchema,
                    RequirementSpec, SecuritySpec,
                )
                warnings.append(
                    f"No registry available; using placeholder for '{tmpl_task.id}'"
                )
                matched_caps[tmpl_task.id] = CapabilityManifest(
                    metadata=MetadataSpec(
                        name=tmpl_task.id,
                        version="1.0.0",
                        description=tmpl_task.description or "",
                    ),
                    input_schema={"input": FieldSchema(type="string")},
                    output_schema={"output": FieldSchema(type="string")},
                    requirements=RequirementSpec(),
                    security=SecuritySpec(),
                )
                continue

            if prefer_cheap_caps:
                cap = self._resolve_cheapest_capability(tmpl_task.capability_pattern)
            else:
                cap = self._resolve_capability(tmpl_task.capability_pattern)
            if cap is None:
                raise NoCapabilityMatchError(
                    f"No capability matches pattern '{tmpl_task.capability_pattern}' "
                    f"for task '{tmpl_task.id}'"
                )
            matched_caps[tmpl_task.id] = cap

        # Instantiate tasks with concrete capabilities
        tasks: list[WorkflowTask] = []
        for tmpl_task in template.tasks:
            cap = matched_caps[tmpl_task.id]
            resolved_input = self._resolve_inputs(
                tmpl_task.input_template, goal_fields, {},
            )
            tasks.append(WorkflowTask(
                id=tmpl_task.id,
                capability=cap.id,
                input=resolved_input,
                description=tmpl_task.description,
            ))

        # Instantiate edges
        edges: list[WorkflowEdge] = []
        for tmpl_edge in template.edges:
            edges.append(WorkflowEdge(
                from_task=tmpl_edge.from_task,
                to_task=tmpl_edge.to_task,
                data=tmpl_edge.data_mapping,
            ))

        # Build the spec with optional semantics override
        semantics = template.semantics or ExecutionSemantics.defaults()
        if force_parallel:
            current_strategy = semantics.parallel.strategy
            new_strategy = (
                ParallelStrategy.SEQUENTIAL
                if current_strategy == ParallelStrategy.TASK_PARALLEL
                else ParallelStrategy.TASK_PARALLEL
            )
            semantics = replace(
                semantics,
                parallel=ParallelPolicy(strategy=new_strategy),
            )

        spec = WorkflowSpec(
            name=f"plan_{template.name}",
            version="1.0.0",
            tasks=tasks,
            edges=edges,
            semantics=semantics,
            description=f"Planned workflow for: {goal}",
            goal=goal,
        )

        # Validate and build DAG
        try:
            dag = WorkflowDAG(spec)
        except WorkflowValidationError as exc:
            raise PlanError(f"Workflow validation failed: {exc}") from exc

        return PlanResult(
            workflow_dag=dag,
            template_name=template.name,
            goal=goal,
            matched_capabilities=matched_caps,
            warnings=warnings,
        )

    def _estimate_plan(self, plan: PlanResult) -> CostEstimate:
        """
        Estimate total cost and latency for a complete plan.

        Aggregates per-task estimates from the CostModel across all
        matched capabilities in the plan.

        Args:
            plan: The PlanResult to estimate.

        Returns:
            CostEstimate with aggregated cost, latency, and token usage.
        """
        if self._cost_model is None:
            return CostEstimate(0.0, 0, 0, "low", "default")

        total_cost = 0.0
        total_latency = 0
        total_tokens = 0
        confidences: list[str] = []

        for task_id, cap in plan.matched_capabilities.items():
            est = self._cost_model.estimate(cap, "openai", 1000)
            total_cost += est.cost_usd
            total_latency += est.latency_ms
            total_tokens += est.tokens
            confidences.append(est.confidence)

        # Aggregate confidence conservatively (lowest wins)
        agg_confidence: str = "high"
        if "low" in confidences:
            agg_confidence = "low"
        elif "medium" in confidences:
            agg_confidence = "medium"

        return CostEstimate(
            cost_usd=total_cost,
            latency_ms=total_latency,
            tokens=total_tokens,
            confidence=agg_confidence,
            source="default",
        )
