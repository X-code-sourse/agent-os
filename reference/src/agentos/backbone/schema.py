"""Schema Registry — RFC-0500 §7."""

import json
from datetime import datetime, timezone
from typing import Any


class SchemaRegistry:
    """Event type registration and publish-time validation."""

    def __init__(self):
        self._schemas: dict[str, dict[int, dict]] = {}  # event_type → {version → schema}

    def register(self, event_type: str, version: int, schema: dict[str, Any],
                 *, description: str = "", producer: str = "",
                 consumers: list[str] | None = None) -> None:
        if version in self._schemas.get(event_type, {}):
            raise ValueError(f"Schema {event_type} v{version} already registered")
        self._schemas.setdefault(event_type, {})[version] = {
            "schema": schema,
            "description": description,
            "producer": producer,
            "consumers": consumers or [],
        }

    def validate(self, event_type: str, version: int, payload: dict) -> None:
        entry = self._schemas.get(event_type, {}).get(version)
        if entry is None:
            raise ValueError(f"Schema not registered: {event_type} v{version}")

        schema = entry["schema"]
        required = schema.get("required", [])
        props = schema.get("properties", {})

        for field in required:
            if field not in payload:
                raise ValueError(f"Missing required field '{field}' in {event_type} v{version}")

        for field, value in payload.items():
            if field not in props:
                continue
            prop_schema = props[field]
            self._validate_type(field, value, prop_schema)

    def _validate_type(self, field: str, value: Any, prop_schema: dict):
        kind = prop_schema.get("type")
        if kind == "string":
            if not isinstance(value, str):
                raise TypeError(f"Field '{field}' should be string, got {type(value).__name__}")
            if "pattern" in prop_schema:
                import re
                if not re.match(prop_schema["pattern"], str(value)):
                    raise ValueError(f"Field '{field}' does not match pattern {prop_schema['pattern']}")
        elif kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"Field '{field}' should be integer, got {type(value).__name__}")
        elif kind == "number":
            if not isinstance(value, (int, float)):
                raise TypeError(f"Field '{field}' should be number, got {type(value).__name__}")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise TypeError(f"Field '{field}' should be boolean, got {type(value).__name__}")
        elif kind == "array":
            if not isinstance(value, list):
                raise TypeError(f"Field '{field}' should be array, got {type(value).__name__}")
        elif kind == "object":
            if not isinstance(value, dict):
                raise TypeError(f"Field '{field}' should be object, got {type(value).__name__}")
