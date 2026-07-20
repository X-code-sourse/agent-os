"""Verify all Python modules import without errors."""
mods = [
    "agentos.cli",
    "agentos.llm_executor",
    "agentos.planner",
    "agentos.execution_engine",
    "agentos.reviewer",
    "agentos.reporter",
    "agentos.workflow_loader",
    "agentos.models",
    "agentos.event_bus",
]
import importlib, sys
for name in mods:
    importlib.import_module(name)
    print(f"  OK  {name}")
print(f"All {len(mods)} modules import OK")
