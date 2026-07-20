"""Validate sec-filing-rule.yaml structure."""
import yaml, sys

with open("examples/rules/sec-filing-rule.yaml") as f:
    data = yaml.safe_load(f)

assert data["rule_id"] == "rule://finance/sec-filing", f"rule_id: {data['rule_id']}"
assert len(data.get("constraints", [])) > 0, "no constraints"
assert data["governance"]["status"] == "approved", f"status: {data['governance']['status']}"
print(f"Rule OK: {data['rule_id']} ({len(data['constraints'])} constraints)")
