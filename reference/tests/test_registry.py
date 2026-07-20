"""Tests for Registry (RFC-0300)."""

import pytest
from pathlib import Path

from agentos.registry import (
    CapabilityManifest, WorkflowManifest,
    CapabilityRegistry, WorkflowRegistry, AgentOSRegistry,
)
from agentos.backbone.bus import EventBus


class TestCapabilityManifest:
    def test_create(self):
        m = CapabilityManifest(task_type="echo", display_name="Echo")
        assert m.task_type == "echo"
        assert m.enabled is True
        assert m.version == "0.1.0"

    def test_with_fn(self):
        def fn(t, c): return t
        m = CapabilityManifest(task_type="echo", fn=fn)
        assert m.fn is not None


class TestCapabilityRegistry:
    def test_register_and_resolve(self):
        r = CapabilityRegistry()
        r.register("echo", lambda t, c: t, display_name="Echo")
        m = r.resolve("echo")
        assert m is not None
        assert m.task_type == "echo"
        assert m.display_name == "Echo"

    def test_register_manifest(self):
        r = CapabilityRegistry()
        m = CapabilityManifest(task_type="x", description="test")
        r.register_manifest(m)
        assert r.resolve("x") is m

    def test_list(self):
        r = CapabilityRegistry()
        r.register("a", lambda t, c: 1)
        r.register("b", lambda t, c: 2)
        assert len(r.list()) == 2

    def test_list_enabled(self):
        r = CapabilityRegistry()
        r.register("a", lambda t, c: 1)
        m = CapabilityManifest(task_type="b", enabled=False, fn=lambda t, c: 2)
        r.register_manifest(m)
        assert len(r.list()) == 2
        assert len(r.list_enabled()) == 1

    def test_count(self):
        r = CapabilityRegistry()
        assert r.count == 0
        r.register("a", lambda t, c: 1)
        assert r.count == 1

    def test_publishes_event(self):
        bus = EventBus()
        events = []
        bus.subscribe("Registry:", lambda e: events.append(e.event_type))
        r = CapabilityRegistry(bus=bus)
        r.register("x", lambda t, c: None)
        assert "Registry:CapabilityRegistered" in events


class TestWorkflowRegistry:
    def test_track_and_resolve(self):
        r = WorkflowRegistry()
        r.track("wf1", name="Test WF", task_count=3, capability_types={"search", "llm"})
        m = r.resolve("wf1")
        assert m is not None
        assert m.id == "wf1"
        assert m.task_count == 3
        assert "search" in m.capability_types

    def test_reverse_index(self):
        r = WorkflowRegistry()
        r.track("wf1", capability_types={"search", "llm"})
        r.track("wf2", capability_types={"search", "report"})
        wfs = r.workflows_using("search")
        assert len(wfs) == 2
        wfs = r.workflows_using("llm")
        assert len(wfs) == 1
        assert wfs[0].id == "wf1"

    def test_list(self):
        r = WorkflowRegistry()
        r.track("a"); r.track("b")
        assert len(r.list()) == 2

    def test_count(self):
        r = WorkflowRegistry()
        assert r.count == 0
        r.track("a")
        assert r.count == 1

    def test_publishes_event(self):
        bus = EventBus()
        events = []
        bus.subscribe("Registry:", lambda e: events.append(e.event_type))
        r = WorkflowRegistry(bus=bus)
        r.track("x")
        assert "Registry:WorkflowTracked" in events


class TestAgentOSRegistry:
    def test_setup_default(self):
        bus = EventBus()
        reg = AgentOSRegistry.setup_default(bus=bus)
        assert reg.capabilities.count >= 5  # 5 built-in capabilities
        assert reg.resolve_capability("search") is not None
        assert reg.resolve_capability("report") is not None

    def test_snapshot(self):
        reg = AgentOSRegistry.setup_default()
        snap = reg.snapshot()
        assert "capabilities" in snap
        assert "workflows" in snap
        assert len(snap["capabilities"]) >= 5

    def test_engine_integration(self):
        """Engine with registry-backed pool can execute capabilities."""
        from agentos.execution_engine import ExecutionEngine
        from agentos.models import Plan, PlannedTask

        bus = EventBus()
        reg = AgentOSRegistry.setup_default(bus=bus)
        engine = ExecutionEngine(bus=bus, registry=reg)

        plan = Plan(workflow_id="test", tasks=[
            PlannedTask(id="t1", type="search", params={"query": "test"}, depends_on=[]),
        ])
        result = engine.execute(plan)
        assert result.status == "completed"
        assert result.task_results["t1"].status == "completed"
