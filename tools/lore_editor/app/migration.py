from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
import subprocess
from pathlib import Path

from .manifest import CatalogManifest, sha256_bytes
from .storage import ContentStore, canonical_json_bytes


LEGACY_CONFIG_ROOT = Path("config/aphelion/lore_overhaul")
TARGET_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


@dataclass(frozen=True)
class MigrationResult:
	entry_count: int
	group_count: int
	review_count: int
	assignment_count: int


def _read_json(path: Path) -> object:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except FileNotFoundError:
		return None


def _target_slug(type_path: str) -> str:
	slug = TARGET_SLUG_PATTERN.sub("-", type_path.removeprefix("/")).strip("-").casefold()
	return slug or "root"


def _git_revision(repo_root: Path) -> str:
	try:
		completed = subprocess.run(
			["git", "-C", str(repo_root), "rev-parse", "HEAD"],
			check=True,
			capture_output=True,
			text=True,
			encoding="utf-8",
		)
	except (OSError, subprocess.CalledProcessError):
		return "legacy-import"
	return completed.stdout.strip() or "legacy-import"


def _write_bytes(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary_path = path.with_name(f".{path.name}.tmp")
	try:
		temporary_path.write_bytes(content)
		os.replace(temporary_path, path)
	except Exception:
		if temporary_path.exists():
			temporary_path.unlink()
		raise


def _load_entries(entities_root: Path) -> list[dict[str, object]]:
	entries: list[dict[str, object]] = []
	if not entities_root.exists():
		return entries
	for source_path in sorted(entities_root.rglob("*.json"), key=lambda path: path.as_posix()):
		raw_document = _read_json(source_path)
		raw_entries = raw_document if isinstance(raw_document, list) else [raw_document]
		for raw_entry in raw_entries:
			if not isinstance(raw_entry, dict):
				raise ValueError(f"{source_path.as_posix()}: entity document must contain objects.")
			if not isinstance(raw_entry.get("id"), str) or not raw_entry["id"]:
				raise ValueError(f"{source_path.as_posix()}: entity record must contain a string id.")
			entries.append(raw_entry)
	return sorted(entries, key=lambda entry: str(entry["id"]))


def migrate_legacy_corpus(legacy_repo_root: Path, tool_root: Path) -> MigrationResult:
	legacy_root = legacy_repo_root.resolve()
	resolved_tool_root = tool_root.resolve()
	legacy_config_root = legacy_root / LEGACY_CONFIG_ROOT
	if not legacy_config_root.is_dir():
		raise ValueError(f"Legacy lore configuration was not found at {legacy_config_root}.")
	store = ContentStore(resolved_tool_root)
	if any((resolved_tool_root / "content").rglob("*.json")):
		raise ValueError("Standalone content is not empty; migration will not overwrite existing records.")

	entries = _load_entries(legacy_config_root / "entities")
	for entry in entries:
		store.save_record("overrides", entry)

	raw_groups = _read_json(legacy_config_root / "groups.json") or {}
	if not isinstance(raw_groups, dict):
		raise ValueError("Legacy groups.json must contain an object.")
	groups = raw_groups.get("groups", [])
	if not isinstance(groups, list):
		raise ValueError("Legacy groups.json groups must be an array.")
	for group in groups:
		if not isinstance(group, dict) or not isinstance(group.get("id"), str):
			raise ValueError("Legacy group records must contain a string id.")
		store.save_record("groups", group)

	assignments = raw_groups.get("assignments", {})
	if not isinstance(assignments, dict):
		raise ValueError("Legacy groups.json assignments must be an object.")
	for type_path, group_ids in sorted(assignments.items()):
		if not isinstance(type_path, str) or not isinstance(group_ids, list) or any(not isinstance(group_id, str) for group_id in group_ids):
			raise ValueError("Legacy group assignments must map type paths to string arrays.")
		store.save_record("assignments", {
			"id": f"assignment.{_target_slug(type_path)}",
			"type_path": type_path,
			"group_ids": group_ids,
		})

	raw_reviews = _read_json(legacy_config_root / "reviews.json") or {}
	if not isinstance(raw_reviews, dict):
		raise ValueError("Legacy reviews.json must contain an object.")
	reviews = raw_reviews.get("reviews", {})
	if not isinstance(reviews, dict):
		raise ValueError("Legacy reviews.json reviews must be an object.")
	for type_path, review in sorted(reviews.items()):
		if not isinstance(type_path, str) or not isinstance(review, dict):
			raise ValueError("Legacy reviews must map type paths to objects.")
		store.save_record("reviews", {
			"id": f"review.{_target_slug(type_path)}",
			"type_path": type_path,
			**review,
		})

	raw_targets = _read_json(legacy_config_root / "targets.json")
	if not isinstance(raw_targets, list):
		raise ValueError("Legacy targets.json must contain an array.")
	targets_bytes = canonical_json_bytes(raw_targets)
	targets_path = resolved_tool_root / "catalog" / "targets.json"
	_write_bytes(targets_path, targets_bytes)
	manifest = CatalogManifest(
		snapshot_sha256=sha256_bytes(targets_bytes),
		game_repo_revision=_git_revision(legacy_root),
		generated_at=datetime.now(timezone.utc).isoformat(),
		target_count=len(raw_targets),
	)
	_write_bytes(resolved_tool_root / "catalog" / "manifest.json", canonical_json_bytes(manifest.to_dict()))

	return MigrationResult(
		entry_count=len(entries),
		group_count=len(groups),
		review_count=len(reviews),
		assignment_count=len(assignments),
	)
