"""External Capability discovery and loading (RFC-0400 §6)."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..registry import Registry

from ..registry.manifest import load_manifest_from_yaml

logger = logging.getLogger(__name__)


def load_capability(
    path: str | Path,
    registry: Registry | None = None,
) -> CapabilityManifest:
    """Load a single external capability from a directory.

    Expects ``path`` to be a directory containing:
        manifest.yaml   — CapabilityManifest metadata
        handler.py      — implementation (or overridden by entry_point in manifest)

    Args:
        path: Directory containing the capability.
        registry: Optional Registry to register into.

    Returns:
        CapabilityManifest with ``fn`` populated.

    Raises:
        FileNotFoundError: If manifest.yaml is missing.
        ImportError: If the handler function cannot be imported.
        ValueError: If the manifest is invalid.
    """
    path = Path(path)
    manifest_path = path / "manifest.yaml"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest.yaml found in {path.resolve()}. "
            f"Expected: {manifest_path}"
        )

    manifest = load_manifest_from_yaml(manifest_path)

    # Resolve entry point: "module.attr" or default "handler.handler"
    ep = manifest.entry_point or "handler.handler"
    module_path, attr_name = _parse_entry_point(ep)

    # Build the importable module name
    # The capability directory name becomes the package name
    package_name = path.name

    # Add parent to sys.path so the package is importable
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    try:
        mod = importlib.import_module(f"{package_name}.{module_path}")
    except ModuleNotFoundError as e:
        raise ImportError(
            f"Cannot import handler module '{package_name}.{module_path}': {e}. "
            f"Ensure {path.resolve()} has a valid Python package structure."
        ) from e

    if not hasattr(mod, attr_name):
        raise ImportError(
            f"Entry point '{ep}' resolved to module '{mod.__name__}', "
            f"but it has no attribute '{attr_name}'."
        )

    fn = getattr(mod, attr_name)
    manifest.fn = fn
    manifest.source = "external"

    # Validate manifest + fn signature
    from .validator import validate_capability

    result = validate_capability(manifest)
    if not result["valid"]:
        raise ValueError(
            f"Capability validation failed for '{manifest.task_type}':\n"
            + "\n".join(f"  - {e}" for e in result["errors"])
        )

    # Register with Registry if provided
    if registry is not None:
        registry.register_manifest(manifest.task_type, manifest)
        logger.info("Registered external capability: %s v%s", manifest.task_type, manifest.version)

    return manifest


def discover_capabilities(
    path: str | Path,
    registry: Registry | None = None,
) -> list[CapabilityManifest]:
    """Scan a directory tree for external capabilities.

    Each immediate subdirectory containing a ``manifest.yaml`` is treated as
    a capability and loaded via :func:`load_capability`.

    Args:
        path: Root directory to scan.
        registry: Optional Registry to register discovered capabilities into.

    Returns:
        List of successfully loaded ``CapabilityManifest`` objects.
    """
    path = Path(path)
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    manifests: list[CapabilityManifest] = []

    for entry in sorted(path.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "manifest.yaml").exists():
            continue

        try:
            manifest = load_capability(entry, registry=registry)
            manifests.append(manifest)
        except (FileNotFoundError, ImportError, ValueError) as e:
            logger.warning("Skipping %s: %s", entry.name, e)

    logger.info("Discovered %d external capabilities from %s", len(manifests), path)
    return manifests


def discover_installed(
    registry: Registry | None = None,
    group: str = "agentos.capabilities",
) -> list[CapabilityManifest]:
    """Discover capabilities installed as pip packages via entry points.

    Third-party packages advertise capabilities using the ``agentos.capabilities``
    entry point group in their ``pyproject.toml`` or ``setup.py``.

    Each entry point should expose a factory function that returns a
    ``CapabilityManifest`` with its ``fn`` populated.

    Args:
        registry: Optional Registry to register discovered capabilities into.
        group: Entry point group name (default: ``agentos.capabilities``).

    Returns:
        List of loaded ``CapabilityManifest`` objects.
    """
    from importlib.metadata import entry_points

    manifests: list[CapabilityManifest] = []

    try:
        eps = entry_points(group=group)
    except TypeError:
        # Python < 3.12 compatibility
        eps = entry_points().get(group, [])

    for ep in eps:
        try:
            loader = ep.load()  # returns a callable: () -> CapabilityManifest
            manifest = loader()
            manifest.source = "external"
            manifests.append(manifest)

            if registry is not None:
                registry.register_manifest(manifest.task_type, manifest)
                logger.info("Installed capability: %s v%s", manifest.task_type, manifest.version)
        except Exception as e:
            logger.error("Failed to load installed capability '%s': %s", ep.name, e)

    return manifests


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_entry_point(ep: str) -> tuple[str, str]:
    """Parse 'module.attr' into ('module', 'attr').

    Supports dotted module paths:
        'handler.handler'       -> ('handler', 'handler')
        'subpkg.impl.run'       -> ('subpkg.impl', 'run')
    """
    parts = ep.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid entry_point '{ep}': expected 'module.attr' format"
        )
    return parts[0], parts[1]
