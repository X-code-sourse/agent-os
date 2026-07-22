"""
Intent OS — Federated Registry (SPEC-0006)

Minimal implementation of multi-registry discovery and sync.
Allows one CapabilityRegistry to discover capabilities from peer
registries and import them.

Phase 0: HTTP-based peer query with local caching.
Phase 2+: Peer authentication, trust models, gossip protocol, consensus.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any

from core.registry import CapabilityRegistry
from core.search import SearchIndex


# ── Data Types ──


@dataclass
class PeerInfo:
    """Describes a remote capability registry peer."""

    name: str
    url: str
    description: str = ""
    version: str = "0.1.0"
    capability_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PeerInfo:
        return cls(
            name=d.get("name", "unknown"),
            url=d.get("url", ""),
            description=d.get("description", ""),
            version=d.get("version", "0.1.0"),
            capability_count=d.get("capability_count", 0),
        )


@dataclass
class PeerCapability:
    """A capability discovered from a remote peer."""

    name: str
    version: str
    description: str = ""
    manifest_yaml: str | None = None
    source_peer: str = ""


# ── Exceptions ──


class FederatedRegistryError(Exception):
    """Raised when federated registry operations fail."""
    pass


class PeerUnreachableError(FederatedRegistryError):
    """Raised when a peer registry cannot be contacted."""
    pass


# ── Federated Registry ──


class FederatedRegistry:
    """Registry that can discover and query capabilities from peer registries.

    Maintains a local list of known peers and can:
    - Query a peer for its capability list
    - Search across all known peers
    - Import capabilities from peers into a local CapabilityRegistry
    - Export local capabilities for peers to discover

    Phase 0: Simple HTTP-based peer query.
    Phase 2+: Gossip protocol, trust scoring, conflict resolution.
    """

    def __init__(
        self,
        local_registry: CapabilityRegistry | None = None,
        search_index: SearchIndex | None = None,
    ) -> None:
        self._local_registry = local_registry
        self._search_index = search_index
        self._peers: dict[str, PeerInfo] = {}

    # ── Peer Management ──

    @property
    def peers(self) -> dict[str, PeerInfo]:
        """Known peer registries (name -> PeerInfo)."""
        return dict(self._peers)

    def register_peer(self, peer: PeerInfo) -> None:
        """Add or update a known peer registry."""
        self._peers[peer.name] = peer

    def unregister_peer(self, name: str) -> None:
        """Remove a known peer."""
        self._peers.pop(name, None)

    def get_peer(self, name: str) -> PeerInfo | None:
        """Look up a peer by name."""
        return self._peers.get(name)

    # ── Peer Discovery ──

    def query_peer_capabilities(
        self,
        peer_name: str,
        query: str | None = None,
        timeout: int = 10,
    ) -> list[PeerCapability]:
        """Query a peer for its capabilities (locally cached or via HTTP).

        Args:
            peer_name: Name of the peer to query.
            query: Optional search query (None = list all).
            timeout: HTTP request timeout in seconds.

        Returns:
            List of PeerCapability objects.

        Raises:
            PeerUnreachableError: If the peer cannot be contacted.
            FederatedRegistryError: On other errors.
        """
        peer = self._peers.get(peer_name)
        if peer is None:
            raise FederatedRegistryError(f"Unknown peer: {peer_name}")

        # Phase 0: only local / HTTP JSON fetch
        import urllib.request

        params = f"?q={urllib.request.quote(query)}" if query else ""
        url = f"{peer.url}/api/v1/capabilities{params}"

        try:
            req = urllib.request.Request(url, method="GET",
                                         headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise PeerUnreachableError(
                f"Peer '{peer_name}' at {url} unreachable: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise FederatedRegistryError(
                f"Peer '{peer_name}' returned unexpected format"
            )

        results: list[PeerCapability] = []
        for item in data:
            results.append(PeerCapability(
                name=item.get("name", "?"),
                version=item.get("version", "?"),
                description=item.get("description", ""),
                manifest_yaml=item.get("manifest_yaml"),
                source_peer=peer_name,
            ))
        return results

    def search_peers(
        self,
        query: str,
        timeout: int = 10,
    ) -> dict[str, list[PeerCapability]]:
        """Search for a capability across all known peers.

        Returns a dict mapping peer_name -> list of matching capabilities.
        Unreachable peers are silently skipped.
        """
        results: dict[str, list[PeerCapability]] = {}
        for peer_name in self._peers:
            try:
                matches = self.query_peer_capabilities(peer_name, query, timeout)
                if matches:
                    results[peer_name] = matches
            except Exception:
                pass  # Skip unreachable peers
        return results

    # ── Import ──

    def import_from_peer(
        self,
        peer_name: str,
        capability_name: str,
        version: str | None = None,
    ) -> bool:
        """Import a capability from a peer into the local registry.

        Args:
            peer_name: Peer to import from.
            capability_name: Name of the capability to import.
            version: Specific version (None = latest).

        Returns:
            True if imported successfully.
        """
        if self._local_registry is None:
            raise FederatedRegistryError("No local registry configured")

        caps = self.query_peer_capabilities(peer_name, capability_name)
        matches = [c for c in caps if c.name == capability_name]
        if version:
            matches = [c for c in matches if c.version == version]

        if not matches or not matches[0].manifest_yaml:
            raise FederatedRegistryError(
                f"Capability '{capability_name}' not found at peer '{peer_name}'"
            )

        from core.parser import parse_manifest

        manifest, validation = parse_manifest(matches[0].manifest_yaml)
        if not validation.valid:
            raise FederatedRegistryError(
                f"Invalid manifest from peer: {[e.message for e in validation.errors]}"
            )

        self._local_registry.register(manifest)
        if self._search_index:
            self._search_index.index(manifest)
        return True

    # ── Export ──

    def export_manifest_list(self) -> list[dict[str, Any]]:
        """Return the local registry's capabilities in a format suitable
        for peer discovery (JSON-serializable list)."""
        if self._local_registry is None:
            return []
        return self._local_registry.list_capabilities()

    # ── Serialization ──

    def to_dict(self) -> dict[str, Any]:
        """Serialize peer list for persistence."""
        return {
            "peers": {n: p.to_dict() for n, p in self._peers.items()},
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        local_registry: CapabilityRegistry | None = None,
        search_index: SearchIndex | None = None,
    ) -> FederatedRegistry:
        """Deserialize from dict."""
        fr = cls(local_registry=local_registry, search_index=search_index)
        for name, peer_data in data.get("peers", {}).items():
            fr._peers[name] = PeerInfo.from_dict(peer_data)
        return fr
