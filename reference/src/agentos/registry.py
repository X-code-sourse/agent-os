"""Agent OS Registry — RFC-0300.

Capability and Workflow registration, discovery, and cross-indexing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from collections import defaultdict

from .backbone.bus import EventBus
from .backbone.event import Event

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────

@dataclass
class CapabilityManifest:
    """Structured metadata for a registered Capability (RFC-0300 §4)."""
    task_type: str
    display_name: str = ""
    description: str = ""
    version: str = "0.1.0"
    input_schema: dict | None = None
    output_schema: dict | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True
    fn: Callable | None = None


@dataclass
class WorkflowManifest:
    """Minimal manifest for a tracked Workflow (RFC-0300 §5)."""
    id: str
    name: str = ""
    description: str = ""
    task_count: int = 0
    capability_types: set[str] = field(default_factory=set)
    path: str = ""
    version: str = "0.1.0"


# ── CapabilityRegistry ────────────────────────────────────────────

class CapabilityRegistry:
    """Structured registry for Capability metadata + callable, with events."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus
        self._by_type: dict[str, CapabilityManifest] = {}

    # ── Registration ──────────────────────────────────────────────

    def register_manifest(
        self,
        manifest: CapabilityManifest,
        source: str | None = None,
    ) -> None:
        """Register a capability manifest. Publishes Registry:CapabilityRegistered."""
        key = manifest.task_type
        if source:
            manifest.source = source
        self._by_type[key] = manifest
        logger.debug("Registry: capability %s v%s registered", key, manifest.version)
        self._publish("Registry:CapabilityRegistered", {
            "task_type": key,
            "version": manifest.version,
            "source": manifest.source,
        })

    def register(
        self,
        task_type: str,
        fn: Callable,
        *,
        display_name: str = "",
        version: str = "0.1.0",
        tags: list[str] | None = None,
    ) -> None:
        """Convenience: create a manifest and register at once."""
        manifest = CapabilityManifest(
            task_type=task_type,
            display_name=display_name or task_type,
            version=version,
            tags=tags or [],
            fn=fn,
        )
        self.register_manifest(manifest)

    # ── Query ─────────────────────────────────────────────────────

    def resolve(self, task_type: str) -> CapabilityManifest | None:
        return self._by_type.get(task_type)

    def list(self) -> list[CapabilityManifest]:
        return list(self._by_type.values())

    def list_enabled(self) -> list[CapabilityManifest]:
        return [m for m in self._by_type.values() if m.enabled]

    @property
    def count(self) -> int:
        return len(self._by_type)

    # ── Publish ───────────────────────────────────────────────────

    def _publish(self, event_type: str, payload: dict) -> None:
        if not self._bus:
            return
        self._bus.publish(Event.new(
            event_type=event_type,
            payload=payload,
            source={"module": "registry", "instance_id": ""},
        ))


# ── WorkflowRegistry ──────────────────────────────────────────────

class WorkflowRegistry:
    """Indexes Workflow metadata with lazy scanning, caching, and reverse index."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus
        self._by_id: dict[str, WorkflowManifest] = {}
        self._by_capability: dict[str, set[str]] = defaultdict(set)  # task_type → {wf_ids}
        self._scanned_dirs: set[str] = set()

    def track(self, wf_id: str, *, name: str = "", path: str = "",
              task_count: int = 0, capability_types: set[str] | None = None) -> None:
        """Register or update a workflow manifest."""
        existing = self._by_id.get(wf_id)
        if existing:
            # Update reverse index for removed capability types
            old_caps = existing.capability_types - (capability_types or set())
            for ct in old_caps:
                self._by_capability[ct].discard(wf_id)

        manifest = WorkflowManifest(
            id=wf_id,
            name=name or wf_id,
            path=path,
            task_count=task_count,
            capability_types=capability_types or set(),
        )
        self._by_id[wf_id] = manifest

        # Build reverse index
        for ct in (capability_types or set()):
            self._by_capability[ct].add(wf_id)

        self._publish("Registry:WorkflowTracked", {
            "workflow_id": wf_id,
            "task_count": task_count,
            "capability_types": sorted(manifest.capability_types),
        })

    def scan(self, extra_dirs: list[Path] | None = None) -> int:
        """Scan workflow directories and index found workflows. Returns count."""
        from .workflow_loader import WORKFLOW_DIRS
        dirs = list(WORKFLOW_DIRS)
        if extra_dirs:
            dirs.extend(extra_dirs)

        found = 0
        for d in dirs:
            resolved = Path(d).resolve()
            resolved_s = str(resolved)
            if resolved_s in self._scanned_dirs:
                continue
            self._scanned_dirs.add(resolved_s)

            if not resolved.is_dir():
                continue
            for f in resolved.glob("*.yaml"):
                try:
                    import yaml
                    with open(f) as fh:
                        raw = yaml.safe_load(fh)
                    wf_id = raw.get("id", f.stem)
                    tasks = raw.get("tasks", [])
                    caps = set()
                    for t in tasks:
                        if isinstance(t, dict) and "type" in t:
                            caps.add(t["type"])
                    self.track(
                        wf_id, name=raw.get("name", wf_id), path=str(f),
                        task_count=len(tasks), capability_types=caps,
                    )
                    found += 1
                except Exception as e:
                    logger.warning("Registry: failed to scan %s: %s", f, e)

        if found:
            self._publish("Registry:ScanComplete", {"workflow_count": found})
        return found

    def resolve(self, wf_id: str) -> WorkflowManifest | None:
        return self._by_id.get(wf_id)

    def list(self) -> list[WorkflowManifest]:
        return list(self._by_id.values())

    def workflows_using(self, task_type: str) -> list[WorkflowManifest]:
        """Reverse lookup: which workflows use a given capability type."""
        wf_ids = self._by_capability.get(task_type, set())
        return [self._by_id[wid] for wid in wf_ids if wid in self._by_id]

    @property
    def count(self) -> int:
        return len(self._by_id)

    def _publish(self, event_type: str, payload: dict) -> None:
        if not self._bus:
            return
        self._bus.publish(Event.new(
            event_type=event_type,
            payload=payload,
            source={"module": "registry", "instance_id": ""},
        ))


# ── Unified Registry ──────────────────────────────────────────────

class AgentOSRegistry:
    """Unified entry point combining CapabilityRegistry + WorkflowRegistry."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self.capabilities = CapabilityRegistry(bus=bus)
        self.workflows = WorkflowRegistry(bus=bus)
        self._bus = bus

    @classmethod
    def setup_default(
        cls,
        bus: EventBus | None = None,
        extra_workflow_dirs: list[Path] | None = None,
    ) -> "AgentOSRegistry":
        """Create Registry and load all default entries.

        1. Load built-in Capabilities from capabilities module
        2. Scan workflow directories
        3. Publish Registry:Initialized event
        """
        registry = cls(bus=bus)

        # Load built-in Capabilities
        from .capabilities import CAPABILITY_MANIFESTS
        for manifest in CAPABILITY_MANIFESTS:
            registry.capabilities.register_manifest(manifest)

        # Scan workflow directories
        registry.workflows.scan(extra_dirs=extra_workflow_dirs)

        if bus:
            bus.publish(Event.new(
                "Registry:Initialized",
                payload={
                    "capability_count": registry.capabilities.count,
                    "workflow_count": registry.workflows.count,
                },
                source={"module": "registry", "instance_id": ""},
            ))

        return registry

    def resolve_workflow(self, wf_id: str) -> WorkflowManifest | None:
        return self.workflows.resolve(wf_id)

    def resolve_capability(self, task_type: str) -> CapabilityManifest | None:
        return self.capabilities.resolve(task_type)

    def workflows_using(self, task_type: str) -> list[WorkflowManifest]:
        return self.workflows.workflows_using(task_type)

    def snapshot(self) -> dict:
        return {
            "capabilities": [
                {"task_type": m.task_type, "version": m.version,
                 "source": m.source, "enabled": m.enabled}
                for m in self.capabilities.list()
            ],
            "workflows": [
                {"id": m.id, "task_count": m.task_count,
                 "capability_types": sorted(m.capability_types)}
                for m in self.workflows.list()
            ],
        }
