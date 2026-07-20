"""Validate all JSON Schema files in schemas/."""
import json, glob, sys, os

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
found = 0
for path in glob.glob(os.path.join(base, "schemas", "**", "*.json"), recursive=True):
    with open(path) as f:
        s = json.load(f)
    assert "$schema" in s, f"Missing $schema in {path}"
    found += 1
    print(f"Schema: {s.get('title', '?')} ({path})")

assert found > 0, "No schema files found"
print(f"Schemas OK: {found} file(s)")
