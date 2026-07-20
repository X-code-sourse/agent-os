"""E2E verification: validate run --json output."""
import json, sys

with open("/tmp/e2e.json") as f:
    d = json.load(f)

assert d["execution"]["status"] == "completed", f"status: {d['execution']['status']}"
assert len(d["tasks"]) == 5, f"tasks: {len(d['tasks'])}"
assert d["review"]["result"] == "pass", f"review: {d['review']['result']}"
print(f"E2E PASS: {len(d['tasks'])} tasks, review={d['review']['result']}")
