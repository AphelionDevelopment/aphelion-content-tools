from __future__ import annotations

from dataclasses import dataclass

from webapp.manifest_base import (
	MANIFEST_FORMAT_VERSION,
	required_string as _required_string,
	sha256_bytes,
)

__all__ = ["MANIFEST_FORMAT_VERSION", "sha256_bytes", "GraphManifest"]


@dataclass(frozen=True)
class GraphManifest:
	snapshot_sha256: str
	game_repo_revision: str
	generated_at: str
	node_count: int
	edge_count: int
	module_count: int
	master_files_count: int
	marker_count: int
	file_count: int = 0
	directory_count: int = 0
	reference_count: int = 0
	format_version: int = MANIFEST_FORMAT_VERSION

	def to_dict(self) -> dict[str, object]:
		return {
			"format_version": self.format_version,
			"snapshot_sha256": self.snapshot_sha256,
			"game_repo_revision": self.game_repo_revision,
			"generated_at": self.generated_at,
			"node_count": self.node_count,
			"edge_count": self.edge_count,
			"module_count": self.module_count,
			"master_files_count": self.master_files_count,
			"marker_count": self.marker_count,
			"file_count": self.file_count,
			"directory_count": self.directory_count,
			"reference_count": self.reference_count,
		}

	@classmethod
	def from_dict(cls, payload: object) -> "GraphManifest":
		if not isinstance(payload, dict):
			raise ValueError("Graph manifest must be a JSON object.")
		if payload.get("format_version") != MANIFEST_FORMAT_VERSION:
			raise ValueError("Unsupported graph manifest format version.")
		counts = {}
		for field_name in ("node_count", "edge_count", "module_count", "master_files_count", "marker_count"):
			value = payload.get(field_name)
			if not isinstance(value, int) or value < 0:
				raise ValueError(f"Graph manifest {field_name} must be a non-negative integer.")
			counts[field_name] = value
		for field_name in ("file_count", "directory_count", "reference_count"):
			value = payload.get(field_name, 0)
			if not isinstance(value, int) or value < 0:
				raise ValueError(f"Graph manifest {field_name} must be a non-negative integer.")
			counts[field_name] = value
		return cls(
			snapshot_sha256=_required_string(payload, "snapshot_sha256"),
			game_repo_revision=_required_string(payload, "game_repo_revision"),
			generated_at=_required_string(payload, "generated_at"),
			**counts,
		)
