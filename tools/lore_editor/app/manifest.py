from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping


MANIFEST_FORMAT_VERSION = 1


def sha256_bytes(value: bytes) -> str:
	return hashlib.sha256(value).hexdigest()


def _required_string(payload: Mapping[str, object], field_name: str) -> str:
	value = payload.get(field_name)
	if not isinstance(value, str) or not value:
		raise ValueError(f"Manifest field '{field_name}' must be a non-empty string.")
	return value


def _required_string_list(payload: Mapping[str, object], field_name: str) -> tuple[str, ...]:
	value = payload.get(field_name)
	if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
		raise ValueError(f"Manifest field '{field_name}' must be an array of non-empty strings.")
	return tuple(value)


@dataclass(frozen=True)
class CatalogManifest:
	snapshot_sha256: str
	game_repo_revision: str
	generated_at: str
	target_count: int
	format_version: int = MANIFEST_FORMAT_VERSION

	def to_dict(self) -> dict[str, object]:
		return {
			"format_version": self.format_version,
			"snapshot_sha256": self.snapshot_sha256,
			"game_repo_revision": self.game_repo_revision,
			"generated_at": self.generated_at,
			"target_count": self.target_count,
		}

	@classmethod
	def from_dict(cls, payload: object) -> "CatalogManifest":
		if not isinstance(payload, dict):
			raise ValueError("Catalog manifest must be a JSON object.")
		if payload.get("format_version") != MANIFEST_FORMAT_VERSION:
			raise ValueError("Unsupported catalog manifest format version.")
		target_count = payload.get("target_count")
		if not isinstance(target_count, int) or target_count < 0:
			raise ValueError("Catalog manifest target_count must be a non-negative integer.")
		return cls(
			snapshot_sha256=_required_string(payload, "snapshot_sha256"),
			game_repo_revision=_required_string(payload, "game_repo_revision"),
			generated_at=_required_string(payload, "generated_at"),
			target_count=target_count,
		)


@dataclass(frozen=True)
class ExportManifest:
	tool_repo_revision: str
	tool_branch: str
	catalog_sha256: str
	game_repo_revision: str
	entry_ids: tuple[str, ...]
	type_paths: tuple[str, ...]
	generated_artifact_sha256: str
	base_artifact_sha256: str | None = None
	format_version: int = MANIFEST_FORMAT_VERSION

	def to_dict(self) -> dict[str, object]:
		return {
			"format_version": self.format_version,
			"tool_repo_revision": self.tool_repo_revision,
			"tool_branch": self.tool_branch,
			"catalog_sha256": self.catalog_sha256,
			"game_repo_revision": self.game_repo_revision,
			"entry_ids": list(self.entry_ids),
			"type_paths": list(self.type_paths),
			"generated_artifact_sha256": self.generated_artifact_sha256,
			"base_artifact_sha256": self.base_artifact_sha256,
			"validation": {"valid": True, "issues": []},
		}

	@classmethod
	def from_dict(cls, payload: object) -> "ExportManifest":
		if not isinstance(payload, dict):
			raise ValueError("Export manifest must be a JSON object.")
		if payload.get("format_version") != MANIFEST_FORMAT_VERSION:
			raise ValueError("Unsupported export manifest format version.")
		validation = payload.get("validation")
		if not isinstance(validation, dict) or validation.get("valid") is not True or validation.get("issues") != []:
			raise ValueError("Export manifest validation must be successful with no issues.")
		base_artifact_sha256 = payload.get("base_artifact_sha256")
		if base_artifact_sha256 is not None and (not isinstance(base_artifact_sha256, str) or not base_artifact_sha256):
			raise ValueError("Export manifest base_artifact_sha256 must be a non-empty string or null.")
		return cls(
			tool_repo_revision=_required_string(payload, "tool_repo_revision"),
			tool_branch=_required_string(payload, "tool_branch"),
			catalog_sha256=_required_string(payload, "catalog_sha256"),
			game_repo_revision=_required_string(payload, "game_repo_revision"),
			entry_ids=_required_string_list(payload, "entry_ids"),
			type_paths=_required_string_list(payload, "type_paths"),
			generated_artifact_sha256=_required_string(payload, "generated_artifact_sha256"),
			base_artifact_sha256=base_artifact_sha256,
		)
