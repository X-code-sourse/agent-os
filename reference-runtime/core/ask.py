"""
Intent OS — Ask Session: natural language intent → capability execution.

The AskSession class is the primary user-facing entry point for the Intent OS
reference runtime.  It takes a free-text user request and:

  1. Classifies the intent against registered capabilities
  2. Resolves (or generates) a capability manifest
  3. Extracts input parameters from the user's text
  4. Executes the capability via the Executor
  5. Summarises the result in natural language
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from core.llm_provider import ProviderFactory
from core.ask_preferences import PreferencesStore
from core.registry import CapabilityRegistry
from core.executor import Executor, ExecutionError
from core.parser import parse_manifest
from core.models import (
    CapabilityManifest,
    MetadataSpec,
    FieldSchema,
    SecuritySpec,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AskResult:
    """Complete result of one :meth:`AskSession.process` call."""

    success: bool
    summary: str
    record: dict
    manifest_created: bool = False
    error: str | None = None


@dataclass
class Intent:
    """Structured interpretation of the user's free-text request."""

    action: str
    capability_name: str | None = None
    confidence: float = 0.0
    input_fields: dict[str, Any] = field(default_factory=dict)
    preferred_adapter: str | None = None
    missing_info: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = """\
You are an intent classifier for the Intent OS runtime.  Your job is to determine \
which registered capability the user wants to invoke and extract any parameters \
they have already provided.

Available capabilities:
{capabilities}

Return a JSON object with these fields:
- "action": a short verb phrase describing what the user wants to do
- "capability_name": the **exact** name (without @version) of the best-matching \
capability, or null if none matches well enough
- "confidence": a float from 0.0 to 1.0 indicating how sure you are about the match
- "input_fields": a dict of any parameter values the user already mentioned, \
keyed by parameter name.  Omit any field whose value is not yet known.
- "preferred_adapter": if the user names a specific runtime/adapter, put it \
here; otherwise null
- "missing_info": a list of field names (from the matched capability's input \
schema) that the user did **not** provide values for

Be conservative: if no capability is a reasonable match, set confidence to 0.0 \
and capability_name to null."""

_GENERATE_MANIFEST_PROMPT = """\
You are a capability manifest generator for the Intent OS.  Given a user request \
and an action description, produce a valid YAML Capability Manifest.

The manifest must follow this structure:

kind: Capability
metadata:
  name: <short-kebab-case-name>
  version: 1.0.0
  publisher: intent-os
  description: <one-line description of what this capability does>
  tags: [<relevant-tags>]
spec:
  input:
    <field-name>:
      type: <string|integer|number|boolean|array|object>
      description: <what the field is for>
      optional: <true|false>
  output:
    <field-name>:
      type: <string|integer|number|boolean|array|object>
      description: <what the field contains>
  security:
    risk: low
    require_approval: false

Return ONLY the YAML -- no explanations, no markdown fences."""

_EXTRACT_PARAMS_PROMPT = """\
You are a parameter extraction assistant.  Given a user request and the input \
schema of the capability being invoked, extract the values for each parameter.

User request: {user_input}

Input schema:
{input_schema}

Return a JSON object where each key is a parameter name and each value is the \
extracted value.  For optional parameters with no provided value, either omit \
the key or set it to null.  Infer reasonable values from the context when the \
user's text implies them but does not spell them out explicitly."""

_SUMMARIZE_PROMPT = """\
You are a summariser for the Intent OS runtime.  Given an execution record, \
produce a concise 1--3 sentence natural-language summary of what happened and \
the outcome.

Execution record:
{record_json}

Return a JSON object with a single field "summary" containing the text."""


# ---------------------------------------------------------------------------
# AskSession
# ---------------------------------------------------------------------------


class AskSession:
    """Interactive session that processes natural language requests.

    Walks through the full Ask pipeline::

        classify -> resolve manifest -> extract params -> execute -> summarise

    Parameters
    ----------
    registry:
        Capability registry used to look up and store manifests.
    executor:
        Execution engine that invokes capabilities.
    llm_provider:
        An :class:`~core.llm_provider.LLMProvider` instance used for all
        LLM calls (classification, manifest generation, extraction,
        summarisation).
    preferences:
        Optional preference store.  A fresh :class:`PreferencesStore`
        is created when not provided.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        executor: Executor,
        llm_provider: Any,
        preferences: PreferencesStore | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._llm = llm_provider
        self._preferences = preferences or PreferencesStore()
        self._pending_manifest_yaml: str | None = None

    # -- public API ---------------------------------------------------------

    def process(self, user_input: str) -> AskResult:
        """Process a free-text user request through the full Ask pipeline.

        Args:
            user_input: The user's natural language request.

        Returns:
            An :class:`AskResult` describing the outcome.
        """
        try:
            # Step 1 -- classify the user's intent
            intent = self._classify_intent(user_input)

            # Step 2 -- resolve or generate a capability manifest
            manifest, created = self._resolve_manifest(intent)

            if manifest is None:
                return AskResult(
                    success=False,
                    summary="Could not resolve or generate a capability manifest.",
                    record={},
                    manifest_created=False,
                    error="No matching capability and unable to generate one.",
                )

            # Step 3 -- extract input parameters
            params = self._extract_params(intent, manifest, user_input)

            # Step 4 -- execute the capability
            record = self._execute(manifest, params, intent.preferred_adapter)

            # Step 5 -- summarise the result
            summary = self._summarize(record)

            return AskResult(
                success=record.status.value == "success",
                summary=summary,
                record=record.to_dict() if hasattr(record, "to_dict") else {},
                manifest_created=created,
                error=None,
            )

        except Exception as exc:
            return AskResult(
                success=False,
                summary="An error occurred while processing your request.",
                record={},
                manifest_created=False,
                error=str(exc),
            )

    # -- pipeline steps -----------------------------------------------------

    def _classify_intent(self, text: str) -> Intent:
        """Build a prompt listing ALL registry capabilities, call the LLM,
        and return a structured :class:`Intent`."""
        capabilities = self._registry.list_capabilities()
        caps_text = _format_capabilities(capabilities)

        messages = [
            {
                "role": "system",
                "content": _CLASSIFY_SYSTEM_PROMPT.format(
                    capabilities=caps_text,
                ),
            },
            {"role": "user", "content": text},
        ]

        try:
            raw = self._llm.chat_json(messages)
        except Exception:
            return Intent(action=text, capability_name=None, confidence=0.0)

        return Intent(
            action=raw.get("action", text),
            capability_name=raw.get("capability_name"),
            confidence=float(raw.get("confidence", 0.0)),
            input_fields=raw.get("input_fields", {}),
            preferred_adapter=raw.get("preferred_adapter"),
            missing_info=raw.get("missing_info", []),
        )

    def _resolve_manifest(
        self,
        intent: Intent,
    ) -> tuple[Optional[CapabilityManifest], bool]:
        """Resolve a :class:`CapabilityManifest` for the given intent.

        * If the intent names a capability with sufficient confidence
          (``confidence > 0.6``), the registry's semantic search
          (:meth:`CapabilityRegistry.find_by_text`) is used to locate it.
        * Otherwise the LLM generates a fresh YAML manifest, which is
          parsed and registered on the fly.

        Returns
        -------
        ``(manifest, created)`` where *created* is ``True`` when the
        manifest was generated (and registered) rather than looked up.
        """
        manifest: Optional[CapabilityManifest] = None
        created = False

        if intent.capability_name and intent.confidence > 0.6:
            results = self._registry.find_by_text(intent.capability_name)
            if results:
                cap_summary = results[0]["capability"]
                manifest = self._registry.get(cap_summary["name"])

        if manifest is None:
            yaml_text = self._generate_manifest_yaml(intent)
            if yaml_text:
                try:
                    manifest, _ = parse_manifest(yaml_text)
                    # Parse but DON'T auto-register — user decides
                    self._pending_manifest_yaml = yaml_text
                    created = True
                except Exception:
                    pass  # manifest stays None

        return manifest, created

    def confirm_and_register(self) -> bool:
        """Register the pending manifest if the user approves.

        Call this AFTER the user confirms they want to save it.
        Returns True if registered, False if nothing was pending.
        """
        if not self._pending_manifest_yaml:
            return False
        try:
            manifest, _ = parse_manifest(self._pending_manifest_yaml)
            self._registry.register(manifest)
            self._pending_manifest_yaml = None
            return True
        except Exception:
            return False

    @property
    def pending_manifest_yaml(self) -> str | None:
        """The raw YAML of a newly generated manifest, if any."""
        return self._pending_manifest_yaml

    def _generate_manifest_yaml(self, intent: Intent) -> str | None:
        """Call the LLM to generate a YAML capability manifest string."""
        messages = [
            {"role": "system", "content": _GENERATE_MANIFEST_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User request: {intent.action}\n"
                    f"Capability name hint: "
                    f"{intent.capability_name or 'auto-detect'}\n"
                    f"Input fields extracted so far: {intent.input_fields}\n"
                    f"Missing info: {intent.missing_info}\n"
                ),
            },
        ]
        try:
            return self._llm.chat(messages)
        except Exception:
            return None

    def _extract_params(
        self,
        intent: Intent,
        manifest: CapabilityManifest,
        user_input: str,
    ) -> dict[str, Any]:
        """Extract input parameters matching the manifest's schema.

        Starts with whatever ``input_fields`` the classifier already found,
        then calls the LLM against the original user text to fill in any
        remaining gaps.
        """
        schema_lines: list[str] = []
        for name, field in manifest.input_schema.items():
            opt = " (optional)" if field.optional else ""
            desc = field.description or ""
            schema_lines.append(f"  - {name}: {field.type}{opt} -- {desc}")
        schema_text = "\n".join(schema_lines)

        messages = [
            {
                "role": "system",
                "content": _EXTRACT_PARAMS_PROMPT.format(
                    user_input=user_input,
                    input_schema=schema_text,
                ),
            },
        ]

        try:
            raw = self._llm.chat_json(messages)
        except Exception:
            return dict(intent.input_fields)

        # LLM-extracted params override those from the classification step
        merged = dict(intent.input_fields)
        merged.update(raw)
        return merged

    def _execute(
        self,
        manifest: CapabilityManifest,
        params: dict[str, Any],
        adapter: str | None,
    ) -> Any:
        """Execute the capability via the :class:`Executor`."""
        return self._executor.execute(
            manifest=manifest,
            input_data=params,
            adapter_name=adapter,
        )

    def _summarize(self, record: Any) -> str:
        """Produce a natural-language summary of the execution record."""
        record_dict: dict[str, Any] = {}
        if hasattr(record, "to_dict"):
            record_dict = record.to_dict()
        elif isinstance(record, dict):
            record_dict = record

        messages = [
            {
                "role": "system",
                "content": _SUMMARIZE_PROMPT.format(
                    record_json=json.dumps(record_dict, indent=2, default=str),
                ),
            },
        ]
        try:
            raw = self._llm.chat_json(messages)
            return raw.get("summary", "Execution completed.")
        except Exception:
            status = record_dict.get("status", "unknown")
            if status == "success":
                return "The capability executed successfully."
            return f"Execution completed with status: {status}."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_capabilities(capabilities: list[dict[str, Any]]) -> str:
    """Format the capability list for inclusion in the classify prompt."""
    if not capabilities:
        return "(no capabilities are currently registered)"

    lines: list[str] = []
    for cap in capabilities:
        name = cap.get("name", "?")
        desc = cap.get("description", "")
        tags = cap.get("tags", [])
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {name}{tag_str}: {desc}")
    return "\n".join(lines)
