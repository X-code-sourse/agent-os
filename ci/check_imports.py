"""Verify all Python modules import without errors."""
import importlib, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "reference", "src"))

mods = [
    "agentos.cli",
    "agentos.llm_executor",
    "agentos.planner",
    "agentos.execution_engine",
    "agentos.reviewer",
    "agentos.reporter",
    "agentos.workflow_loader",
    "agentos.models",
    "agentos.capabilities",
    "agentos.capabilities.search",
    "agentos.capabilities.llm",
    "agentos.capabilities.review",
    "agentos.capabilities.report",
    "agentos.registry",
]
for name in mods:
    importlib.import_module(name)
    print(f"  OK  {name}")
print(f"All {len(mods)} modules import OK")
