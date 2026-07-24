"""
Intent OS — Capability Manifest Parser

Parses and validates YAML Capability Manifests against SPEC-0001.
Produces a validated CapabilityManifest dataclass instance.

Validation levels:
  - Schema validation: required fields, types, structure
  - Semantic validation: version format, field uniqueness, reference integrity
  - Security validation: risk level defaults, constraint consistency
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from core.models import (
    CapabilityManifest,
    CostSpec,
    FieldSchema,
    MetadataSpec,
    RequirementSpec,
    SecurityRisk,
    SecuritySpec,
    ValidationError,
    ValidationResult,
)


# Version regex: MAJOR.MINOR.PATCH with optional pre-release
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")

# Supported scalar types
_SCALAR_TYPES = {"string", "integer", "number", "boolean"}

# All supported types
_ALL_TYPES = _SCALAR_TYPES | {"array", "object", "any"}


class ManifestParseError(Exception):
    """Raised when a Manifest cannot be parsed or validated."""
    pass


def _parse_field_schema(
    name: str,
    raw: dict,
    path: str,
    errors: list[ValidationError],
) -> FieldSchema | None:
    """Parse a single field schema entry."""
    field_type = raw.get("type", "string")
    if field_type not in _ALL_TYPES:
        errors.append(ValidationError(
            field=f"{path}.{name}",
            message=f"Unsupported type '{field_type}'. Must be one of: {', '.join(sorted(_ALL_TYPES))}",
        ))
        return None

    schema = FieldSchema(
        type=field_type,
        description=raw.get("description"),
        optional=raw.get("optional", False),
        default=raw.get("default"),
    )

    # Type-specific constraints
    if field_type == "string":
        schema.min_length = raw.get("min_length")
        schema.max_length = raw.get("max_length")
        schema.pattern = raw.get("pattern")
        schema.format = raw.get("format")
        schema.enum = raw.get("enum")
    elif field_type in ("integer", "number"):
        schema.minimum = raw.get("minimum")
        schema.maximum = raw.get("maximum")
    elif field_type == "array":
        schema.min_items = raw.get("min_items")
        schema.max_items = raw.get("max_items")
    elif field_type == "array":
        if "items" in raw and isinstance(raw["items"], dict):
            schema.items = _parse_field_schema("items", raw["items"], f"{path}.{name}", errors)
    elif field_type == "object":
        if "properties" in raw and isinstance(raw["properties"], dict):
            schema.properties = {}
            for prop_name, prop_raw in raw["properties"].items():
                parsed = _parse_field_schema(prop_name, prop_raw, f"{path}.{name}", errors)
                if parsed:
                    schema.properties[prop_name] = parsed

    return schema


def _validate_schema_field(
    name: str,
    schema: FieldSchema,
    path: str,
    errors: list[ValidationError],
) -> None:
    """Validate a parsed field schema for consistency."""
    # String constraints only valid for string type
    if schema.type != "string":
        if schema.min_length is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'min_length' is only valid for string type",
            ))
        if schema.max_length is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'max_length' is only valid for string type",
            ))
        if schema.pattern is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'pattern' is only valid for string type",
            ))
        if schema.format is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'format' is only valid for string type",
            ))

    # Numeric constraints only valid for numeric types
    if schema.type not in ("integer", "number"):
        if schema.minimum is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'minimum' is only valid for numeric types",
            ))
        if schema.maximum is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'maximum' is only valid for numeric types",
            ))

    # Array constraints only valid for array type
    if schema.type != "array":
        if schema.min_items is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'min_items' is only valid for array type",
            ))
        if schema.max_items is not None:
            errors.append(ValidationError(
                field=f"{path}.{name}",
                message="'max_items' is only valid for array type",
            ))

    # Recurse into nested schemas
    if schema.properties:
        for prop_name, prop_schema in schema.properties.items():
            _validate_schema_field(prop_name, prop_schema, f"{path}.{name}", errors)
    if schema.items:
        _validate_schema_field("items", schema.items, f"{path}.{name}", errors)


def _compute_digest(raw_yaml: str) -> str:
    """Compute SHA-256 digest of raw YAML content.

    Returns the digest in the canonical ``sha256:...`` prefixed format
    defined by SPEC-0001 Section 3.2.
    """
    return "sha256:" + hashlib.sha256(raw_yaml.encode("utf-8")).hexdigest()


def parse_manifest(source: str | Path) -> tuple[CapabilityManifest, ValidationResult]:
    """
    Parse a Capability Manifest from a YAML file or string.

    Args:
        source: Path to YAML file, or raw YAML string.

    Returns:
        Tuple of (CapabilityManifest, ValidationResult).

    Raises:
        ManifestParseError: If the YAML cannot be parsed.
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationError] = []

    # Read input
    if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
        path = Path(source)
        raw_yaml = path.read_text(encoding="utf-8")
    else:
        raw_yaml = source

    # Parse YAML
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ManifestParseError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ManifestParseError("Manifest must be a YAML mapping (dictionary)")

    # Validate kind
    kind = data.get("kind")
    if kind != "Capability":
        errors.append(ValidationError(
            field="kind",
            message=f"Expected 'Capability', got '{kind}'",
        ))

    # Parse metadata
    raw_metadata = data.get("metadata", {})
    if not isinstance(raw_metadata, dict):
        errors.append(ValidationError(
            field="metadata",
            message="'metadata' must be a mapping",
        ))
        raw_metadata = {}

    name = raw_metadata.get("name", "")
    version = raw_metadata.get("version", "")

    if not name:
        errors.append(ValidationError(field="metadata.name", message="'name' is required"))
    if not version:
        errors.append(ValidationError(field="metadata.version", message="'version' is required"))
    elif not _VERSION_RE.match(version):
        errors.append(ValidationError(
            field="metadata.version",
            message=f"Version '{version}' must follow semantic versioning (MAJOR.MINOR.PATCH)",
        ))

    # Verify digest if present
    declared_digest = raw_metadata.get("digest")
    if declared_digest:
        computed = _compute_digest(raw_yaml)
        # Normalise: strip "sha256:" prefix if present so we can compare
        # old-style (raw hex) and new-style (sha256:hex) declared digests.
        _norm_declared = declared_digest
        if _norm_declared.startswith("sha256:"):
            _norm_declared = _norm_declared[7:]
        _norm_computed = computed[7:]  # strip the "sha256:" we just added
        if _norm_declared != _norm_computed:
            warnings.append(ValidationError(
                field="metadata.digest",
                message=f"Declared digest '{declared_digest}' does not match computed digest '{computed}'",
                severity="warning",
            ))

    metadata = MetadataSpec(
        name=name,
        version=version,
        publisher=raw_metadata.get("publisher"),
        digest=declared_digest or _compute_digest(raw_yaml),
        description=raw_metadata.get("description"),
        tags=raw_metadata.get("tags", []),
    )

    # Parse spec
    raw_spec = data.get("spec", {})
    if not isinstance(raw_spec, dict):
        errors.append(ValidationError(field="spec", message="'spec' must be a mapping"))

    # Parse input schema
    raw_input = raw_spec.get("input", {}) if isinstance(raw_spec, dict) else {}
    if not raw_input:
        errors.append(ValidationError(field="spec.input", message="'spec.input' is required and must have at least one field"))

    input_schema: dict[str, FieldSchema] = {}
    if isinstance(raw_input, dict):
        for field_name, field_raw in raw_input.items():
            parsed = _parse_field_schema(field_name, field_raw, "spec.input", errors)
            if parsed:
                input_schema[field_name] = parsed
                _validate_schema_field(field_name, parsed, "spec.input", errors)

    # Parse output schema
    raw_output = raw_spec.get("output", {}) if isinstance(raw_spec, dict) else {}
    if not raw_output:
        errors.append(ValidationError(field="spec.output", message="'spec.output' is required and must have at least one field"))

    output_schema: dict[str, FieldSchema] = {}
    if isinstance(raw_output, dict):
        for field_name, field_raw in raw_output.items():
            parsed = _parse_field_schema(field_name, field_raw, "spec.output", errors)
            if parsed:
                output_schema[field_name] = parsed
                _validate_schema_field(field_name, parsed, "spec.output", errors)

    # Parse requirements
    raw_reqs = raw_spec.get("requirements", {}) if isinstance(raw_spec, dict) else {}
    requirements = None
    if isinstance(raw_reqs, dict) and raw_reqs:
        requirements = RequirementSpec(
            models=raw_reqs.get("models"),
            tools=raw_reqs.get("tools"),
            min_context=raw_reqs.get("min_context"),
        )
        # Validate min_context if present (SPEC-0001 Section 5.2 Rule 4)
        if requirements.min_context is not None and requirements.min_context < 1024:
            errors.append(ValidationError(
                field="spec.requirements.min_context",
                message=f"min_context must be >= 1024 (got {requirements.min_context})",
            ))

    # Parse security
    raw_security = raw_spec.get("security", {}) if isinstance(raw_spec, dict) else {}
    security = None
    if isinstance(raw_security, dict):
        risk_str = raw_security.get("risk", "low")
        try:
            risk = SecurityRisk(risk_str)
        except ValueError:
            errors.append(ValidationError(
                field="spec.security.risk",
                message=f"Invalid risk level '{risk_str}'. Must be one of: low, medium, high, critical",
            ))
            risk = SecurityRisk.LOW
        security = SecuritySpec(
            risk=risk,
            network=raw_security.get("network", False),
            data_access=raw_security.get("data_access", False),
            require_approval=raw_security.get("require_approval", False),
        )

    # Parse cost
    raw_cost = raw_spec.get("cost", {}) if isinstance(raw_spec, dict) else {}
    cost = None
    if isinstance(raw_cost, dict) and raw_cost:
        cost = CostSpec(
            estimated_tokens=raw_cost.get("estimated_tokens"),
            estimated_latency=raw_cost.get("estimated_latency"),
            pricing_hint=raw_cost.get("pricing_hint"),
        )

    # Build manifest
    manifest = CapabilityManifest(
        metadata=metadata,
        input_schema=input_schema,
        output_schema=output_schema,
        requirements=requirements,
        security=security,
        cost=cost,
    )

    return manifest, ValidationResult(
        valid=len([e for e in errors if e.severity == "error"]) == 0,
        errors=[e for e in errors if e.severity == "error"],
        warnings=[e for e in errors if e.severity == "warning"] + warnings,
    )
