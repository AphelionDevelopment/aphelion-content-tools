from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import tempfile

from .model import CatalogTarget, GroupConfig, GroupRecord, ReviewRecord, thaw_json
from .workspace import WorkspaceLayout


CONFIG_ROOT = Path("config/aphelion/lore_overhaul")
GROUPS_PATH = CONFIG_ROOT / "groups.json"
REVIEWS_PATH = CONFIG_ROOT / "reviews.json"
GROUP_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVIEW_STATUSES = frozenset(("reviewed", "needs-attention"))


def _resolve_path(repo_root: Path, relative_path: Path) -> Path:
	resolved_root = repo_root.resolve()
	resolved_path = (resolved_root / relative_path).resolve()
	if not resolved_path.is_relative_to(resolved_root):
		raise ValueError(f"Repository path escapes root: {relative_path}")
	return resolved_path


def _read_json(repo_root: Path, relative_path: Path, default: object) -> object:
	path = _resolve_path(repo_root, relative_path)
	if not path.exists():
		return default
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except json.JSONDecodeError as exc:
		raise ValueError(f"{relative_path.as_posix()}: malformed JSON at line {exc.lineno} column {exc.colno}: {exc.msg}") from exc


def _atomic_write_json(repo_root: Path, relative_path: Path, payload: object) -> None:
	path = _resolve_path(repo_root, relative_path)
	path.parent.mkdir(parents=True, exist_ok=True)
	content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
	with tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as temporary_file:
		temporary_file.write(content)
		temporary_file.flush()
		os.fsync(temporary_file.fileno())
		temporary_path = Path(temporary_file.name)
	try:
		os.replace(temporary_path, path)
	except Exception:
		if temporary_path.exists():
			temporary_path.unlink()
		raise


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
	if value is None:
		return ()
	if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
		raise ValueError(f"{field_name} must be an array of non-empty strings.")
	return tuple(item.strip() for item in value)


def _validate_group_id(group_id: str) -> None:
	if not GROUP_ID_PATTERN.fullmatch(group_id):
		raise ValueError(f"Invalid group id '{group_id}'. Use lowercase letters, numbers, and hyphens.")


def _group_from_raw(raw_group: object) -> GroupRecord:
	if not isinstance(raw_group, dict):
		raise ValueError("Each group must be a JSON object.")
	group_id = raw_group.get("id")
	label = raw_group.get("label")
	color = raw_group.get("color")
	if not isinstance(group_id, str):
		raise ValueError("Each group must contain a string id.")
	_validate_group_id(group_id)
	if not isinstance(label, str) or not label.strip():
		raise ValueError(f"Group '{group_id}' must contain a non-empty label.")
	if not isinstance(color, str) or not color.strip():
		raise ValueError(f"Group '{group_id}' must contain a non-empty color.")
	type_path_prefixes = _string_tuple(raw_group.get("type_path_prefixes"), f"Group '{group_id}' type_path_prefixes")
	if any(not prefix.startswith("/") for prefix in type_path_prefixes):
		raise ValueError(f"Group '{group_id}' type_path_prefixes must be absolute type paths.")
	return GroupRecord(
		id=group_id,
		label=label.strip(),
		color=color.strip(),
		keywords=_string_tuple(raw_group.get("keywords"), f"Group '{group_id}' keywords"),
		type_path_prefixes=type_path_prefixes,
	)


def _group_payload(group: GroupRecord) -> dict[str, object]:
	return {
		"id": group.id,
		"label": group.label,
		"color": group.color,
		"keywords": list(group.keywords),
		"type_path_prefixes": list(group.type_path_prefixes),
	}


def load_groups(repo_root: Path) -> GroupConfig:
	layout = WorkspaceLayout.from_root(repo_root)
	if layout.standalone:
		groups: list[GroupRecord] = []
		groups_root = _resolve_path(repo_root, layout.content_groups_root)
		if groups_root.exists():
			for group_path in sorted(groups_root.glob("*.json"), key=lambda path: path.name):
				groups.append(_group_from_raw(_read_json(repo_root, layout.content_groups_root / group_path.name, {})))
		group_ids = [group.id for group in groups]
		if len(group_ids) != len(set(group_ids)):
			raise ValueError("Standalone group ids must be unique.")
		assignments: dict[str, tuple[str, ...]] = {}
		assignments_root = _resolve_path(repo_root, layout.content_assignments_root)
		if assignments_root.exists():
			for assignment_path in sorted(assignments_root.glob("*.json"), key=lambda path: path.name):
				record = _read_json(repo_root, layout.content_assignments_root / assignment_path.name, {})
				if not isinstance(record, dict) or not isinstance(record.get("type_path"), str):
					raise ValueError(f"{assignment_path.as_posix()}: assignment must contain a type_path.")
				assigned_group_ids = _string_tuple(record.get("group_ids"), f"Assignment for '{record['type_path']}'")
				if any(group_id not in group_ids for group_id in assigned_group_ids):
					raise ValueError(f"Assignment for '{record['type_path']}' references an unknown group.")
				assignments[record["type_path"]] = assigned_group_ids
		return GroupConfig(groups=tuple(groups), assignments=assignments)
	raw_document = _read_json(repo_root, GROUPS_PATH, {"groups": [], "assignments": {}})
	if not isinstance(raw_document, dict):
		raise ValueError(f"{GROUPS_PATH.as_posix()}: expected a JSON object")
	raw_groups = raw_document.get("groups", [])
	if not isinstance(raw_groups, list):
		raise ValueError(f"{GROUPS_PATH.as_posix()}.groups: expected a JSON array")
	groups = tuple(_group_from_raw(raw_group) for raw_group in raw_groups)
	group_ids = [group.id for group in groups]
	if len(group_ids) != len(set(group_ids)):
		raise ValueError(f"{GROUPS_PATH.as_posix()}: group ids must be unique")
	raw_assignments = raw_document.get("assignments", {})
	if not isinstance(raw_assignments, dict):
		raise ValueError(f"{GROUPS_PATH.as_posix()}.assignments: expected a JSON object")
	assignments: dict[str, tuple[str, ...]] = {}
	for type_path, raw_group_ids in raw_assignments.items():
		if not isinstance(type_path, str) or not type_path.startswith("/"):
			raise ValueError("Group assignments must use absolute type paths.")
		assigned_group_ids = _string_tuple(raw_group_ids, f"Assignment for '{type_path}'")
		if any(group_id not in group_ids for group_id in assigned_group_ids):
			raise ValueError(f"Assignment for '{type_path}' references an unknown group.")
		assignments[type_path] = assigned_group_ids
	return GroupConfig(groups=groups, assignments=assignments)


def _review_from_raw(type_path: str, raw_record: object) -> ReviewRecord:
	if not isinstance(raw_record, dict):
		raise ValueError(f"Review for '{type_path}' must be a JSON object.")
	status = raw_record.get("status")
	reviewed_by = raw_record.get("reviewed_by")
	reviewed_at = raw_record.get("reviewed_at")
	notes = raw_record.get("notes", "")
	if status not in REVIEW_STATUSES:
		raise ValueError(f"Review for '{type_path}' must have status 'reviewed' or 'needs-attention'.")
	if not isinstance(reviewed_by, str) or not reviewed_by.strip():
		raise ValueError(f"Review for '{type_path}' requires reviewed_by.")
	if not isinstance(reviewed_at, str):
		raise ValueError(f"Review for '{type_path}' requires reviewed_at.")
	try:
		datetime.fromisoformat(reviewed_at)
	except ValueError as exc:
		raise ValueError(f"Review for '{type_path}' has an invalid reviewed_at timestamp.") from exc
	if not isinstance(notes, str):
		raise ValueError(f"Review for '{type_path}' notes must be a string.")
	return ReviewRecord(status=status, reviewed_by=reviewed_by.strip(), reviewed_at=reviewed_at, notes=notes)


def load_reviews(repo_root: Path) -> dict[str, ReviewRecord]:
	layout = WorkspaceLayout.from_root(repo_root)
	if layout.standalone:
		reviews: dict[str, ReviewRecord] = {}
		reviews_root = _resolve_path(repo_root, layout.content_reviews_root)
		if reviews_root.exists():
			for review_path in sorted(reviews_root.glob("*.json"), key=lambda path: path.name):
				record = _read_json(repo_root, layout.content_reviews_root / review_path.name, {})
				if not isinstance(record, dict) or not isinstance(record.get("type_path"), str):
					raise ValueError(f"{review_path.as_posix()}: review must contain a type_path.")
				reviews[record["type_path"]] = _review_from_raw(record["type_path"], record)
		return reviews
	raw_document = _read_json(repo_root, REVIEWS_PATH, {"reviews": {}})
	if not isinstance(raw_document, dict) or not isinstance(raw_document.get("reviews", {}), dict):
		raise ValueError(f"{REVIEWS_PATH.as_posix()}: expected an object containing a reviews object")
	reviews: dict[str, ReviewRecord] = {}
	for type_path, raw_record in raw_document["reviews"].items():
		if not isinstance(type_path, str) or not type_path.startswith("/"):
			raise ValueError("Review keys must be absolute type paths.")
		reviews[type_path] = _review_from_raw(type_path, raw_record)
	return reviews


def save_group(repo_root: Path, group: GroupRecord) -> GroupRecord:
	_validate_group_id(group.id)
	_group_from_raw(_group_payload(group))
	config = load_groups(repo_root)
	layout = WorkspaceLayout.from_root(repo_root)
	if layout.standalone:
		_atomic_write_json(repo_root, layout.content_groups_root / f"{group.id}.json", _group_payload(group))
		return group
	updated_groups = [group if existing.id == group.id else existing for existing in config.groups]
	if not any(existing.id == group.id for existing in config.groups):
		updated_groups.append(group)
	payload = {
		"groups": [_group_payload(existing) for existing in updated_groups],
		"assignments": {type_path: list(group_ids) for type_path, group_ids in config.assignments.items()},
	}
	_atomic_write_json(repo_root, GROUPS_PATH, payload)
	return group


def save_group_assignments(repo_root: Path, type_path: str, group_ids: tuple[str, ...]) -> None:
	if not type_path.startswith("/"):
		raise ValueError("Group assignments must use absolute type paths.")
	config = load_groups(repo_root)
	if any(group_id not in {group.id for group in config.groups} for group_id in group_ids):
		raise ValueError("Group assignments reference an unknown group.")
	layout = WorkspaceLayout.from_root(repo_root)
	if layout.standalone:
		assignment_path = _resolve_path(repo_root, layout.content_assignments_root / f"assignment.{_target_slug(type_path)}.json")
		if group_ids:
			_atomic_write_json(repo_root, layout.content_assignments_root / assignment_path.name, {
				"id": assignment_path.stem,
				"type_path": type_path,
				"group_ids": list(group_ids),
			})
		elif assignment_path.exists():
			assignment_path.unlink()
		return
	assignments = dict(config.assignments)
	if group_ids:
		assignments[type_path] = group_ids
	else:
		assignments.pop(type_path, None)
	_atomic_write_json(repo_root, GROUPS_PATH, {
		"groups": [_group_payload(group) for group in config.groups],
		"assignments": {key: list(value) for key, value in assignments.items()},
	})


def save_review(repo_root: Path, type_path: str, record: ReviewRecord | None) -> None:
	if not type_path.startswith("/"):
		raise ValueError("Review keys must be absolute type paths.")
	reviews = load_reviews(repo_root)
	layout = WorkspaceLayout.from_root(repo_root)
	if layout.standalone:
		review_path = _resolve_path(repo_root, layout.content_reviews_root / f"review.{_target_slug(type_path)}.json")
		if record is None:
			if review_path.exists():
				review_path.unlink()
			return
		_atomic_write_json(repo_root, layout.content_reviews_root / review_path.name, {
			"id": review_path.stem,
			"type_path": type_path,
			"status": record.status,
			"reviewed_by": record.reviewed_by,
			"reviewed_at": record.reviewed_at,
			"notes": record.notes,
		})
		return
	if record is None:
		reviews.pop(type_path, None)
	else:
		reviews[type_path] = _review_from_raw(type_path, {
			"status": record.status,
			"reviewed_by": record.reviewed_by,
			"reviewed_at": record.reviewed_at,
			"notes": record.notes,
		})
	_atomic_write_json(repo_root, REVIEWS_PATH, {
		"reviews": {
			type_path: {
				"status": review.status,
				"reviewed_by": review.reviewed_by,
				"reviewed_at": review.reviewed_at,
				"notes": review.notes,
			}
			for type_path, review in sorted(reviews.items())
		},
	})


def _target_slug(type_path: str) -> str:
	return re.sub(r"[^a-zA-Z0-9]+", "-", type_path.removeprefix("/")).strip("-").casefold() or "root"


def _flatten_text(value: object) -> str:
	if isinstance(value, dict):
		return " ".join(_flatten_text(item) for item in value.values())
	if isinstance(value, list):
		return " ".join(_flatten_text(item) for item in value)
	return str(value or "")


@lru_cache(maxsize=256)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
	return re.compile(rf"(?<![a-z0-9]){re.escape(keyword.casefold())}(?![a-z0-9])")


def _keyword_matches(keyword: str, search_text: str) -> bool:
	return _keyword_pattern(keyword).search(search_text) is not None


def _target_search_fields(target: CatalogTarget) -> dict[str, str]:
	raw_target = thaw_json(target.raw_data)
	if not isinstance(raw_target, dict):
		return {}
	base_values = raw_target.get("base_values")
	search_values = {
		"type path": raw_target.get("type_path"),
		"parent type": raw_target.get("parent_type"),
		"label": raw_target.get("label"),
		"name": base_values.get("name") if isinstance(base_values, dict) else None,
		"description": base_values.get("description") if isinstance(base_values, dict) else None,
	}
	search_fields: dict[str, str] = {}
	for field_name, value in search_values.items():
		if value is None:
			continue
		field_text = _flatten_text(value)
		if field_text:
			search_fields[field_name] = field_text
	return search_fields


def classify_target_details(target: CatalogTarget, groups: GroupConfig) -> dict[str, tuple[str, ...]]:
	search_fields = _target_search_fields(target)
	type_path = target.type_path or ""
	assigned_ids = groups.assignments.get(type_path, ())
	classified: dict[str, tuple[str, ...]] = {}
	for group in groups.groups:
		reasons: list[str] = []
		if group.id in assigned_ids:
			reasons.append("manual assignment")
		for prefix in group.type_path_prefixes:
			if type_path == prefix or type_path.startswith(prefix + "/"):
				reasons.append(f"type path prefix '{prefix}'")
		for keyword in group.keywords:
			keyword_pattern = _keyword_pattern(keyword)
			for field_name, field_value in search_fields.items():
				if keyword_pattern.search(field_value.casefold()):
					reasons.append(f"keyword '{keyword}' in {field_name}")
		if reasons:
			classified[group.id] = tuple(reasons)
	return classified


def classify_target(target: CatalogTarget, groups: GroupConfig) -> tuple[str, ...]:
	return tuple(classify_target_details(target, groups))
