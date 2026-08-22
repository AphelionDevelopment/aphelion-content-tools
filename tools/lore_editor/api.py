from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock

from tools.dmi import Dmi

from webapp.git_adapter import find_line_in_tracked_files

from .generate import GENERATED_DM_PATH, write_generated_dm
from .icon_preview import list_icon_files, list_icon_states
from .model import DEFAULT_KEYWORD_SCOPE, GroupConfig, GroupRecord, LoreCorpus, LoreEntry, ReviewRecord, ValidationIssue, thaw_json
from .source import ENTITIES_ROOT, iter_entity_paths, load_corpus, make_lore_entry, read_json_file, resolve_repo_path
from .taxonomy import REVIEW_STATUSES, classify_target_details, load_groups, load_reviews, save_group, save_group_assignments, save_review
from .validation import validate_corpus
from .workspace import WorkspaceLayout


def _issue_payload(issue: ValidationIssue) -> dict[str, str]:
	return {"path": issue.path, "message": issue.message, "severity": issue.severity}


def _target_payload(raw_target: object) -> dict[str, object]:
	if isinstance(raw_target, dict):
		return dict(raw_target)
	return {}


def list_catalog(repo_root: Path) -> list[dict[str, object]]:
	corpus = load_corpus(repo_root)
	targets = [_target_payload(thaw_json(target.raw_data)) for target in corpus.targets]
	targets.sort(key=lambda target: str(target.get("type_path", "")))
	return targets


def list_icon_choices(repo_root: Path, *, asset_root: Path | None = None) -> list[dict[str, object]]:
	resolved_asset_root = (asset_root or repo_root).resolve()
	modules_root = resolve_repo_path(resolved_asset_root, Path("modular_aphelion/modules"))
	if not modules_root.exists():
		return []
	choices: list[dict[str, object]] = []
	for icon_path in sorted(modules_root.rglob("*.dmi"), key=lambda path: path.as_posix()):
		relative_path = icon_path.relative_to(resolved_asset_root)
		parts = relative_path.parts
		if len(parts) < 5 or parts[:2] != ("modular_aphelion", "modules") or parts[3] != "icons":
			continue
		try:
			dmi = Dmi.from_file(icon_path)
		except Exception:
			continue
		choices.append({
			"file": relative_path.as_posix(),
			"states": sorted(state.name for state in dmi.states),
		})
	return choices


def icon_files_response(repo_root: Path, *, asset_root: Path | None = None) -> dict[str, object]:
	return {"files": list_icon_files((asset_root or repo_root).resolve())}


def icon_states_response(repo_root: Path, relative_file: str, *, asset_root: Path | None = None) -> dict[str, object]:
	return {"states": list_icon_states((asset_root or repo_root).resolve(), relative_file)}


def _target_by_type(corpus: LoreCorpus) -> dict[str, dict[str, object]]:
	return {
		str(target.type_path): _target_payload(thaw_json(target.raw_data))
		for target in corpus.targets
		if target.type_path is not None
	}


@dataclass(frozen=True)
class _ReviewCatalogIndex:
	target_by_type: dict[str, dict[str, object]]
	visibility_by_type: dict[str, dict[str, object]]
	target_group_reasons: dict[str, dict[str, tuple[str, ...]]]
	target_groups: dict[str, tuple[str, ...]]


_REVIEW_CATALOG_INDEX_CACHE: dict[tuple[Path, tuple[int, int], tuple[int, int], tuple[int, int]], _ReviewCatalogIndex] = {}
_REVIEW_CATALOG_INDEX_CACHE_LOCK = Lock()


def _file_stamp(path: Path) -> tuple[int, int]:
	try:
		file_stat = path.stat()
	except FileNotFoundError:
		return (0, 0)
	return (file_stat.st_mtime_ns, file_stat.st_size)


def _tree_stamp(path: Path) -> tuple[int, int]:
	if path.is_file():
		return _file_stamp(path)
	if not path.is_dir():
		return (0, 0)
	file_stamps = [_file_stamp(candidate) for candidate in path.rglob("*.json")]
	return (
		sum(stamp[0] for stamp in file_stamps),
		sum(stamp[1] for stamp in file_stamps) + len(file_stamps),
	)


def _review_catalog_index(repo_root: Path, corpus: LoreCorpus, group_config: GroupConfig) -> _ReviewCatalogIndex:
	resolved_root = repo_root.resolve()
	layout = WorkspaceLayout.from_root(resolved_root)
	key = (
		resolved_root,
		_file_stamp(resolve_repo_path(resolved_root, layout.targets_path)),
		_tree_stamp(resolve_repo_path(resolved_root, layout.content_groups_root if layout.standalone else layout.groups_path)),
		_tree_stamp(resolve_repo_path(resolved_root, layout.content_assignments_root)) if layout.standalone else (0, 0),
	)
	with _REVIEW_CATALOG_INDEX_CACHE_LOCK:
		cached_index = _REVIEW_CATALOG_INDEX_CACHE.get(key)
		if cached_index is not None:
			return cached_index

		target_by_type = _target_by_type(corpus)
		target_payloads = tuple(target_by_type.values())
		visibility_by_type = _target_visibility_metadata(target_payloads)
		target_group_reasons = {
			target.type_path: classify_target_details(target, group_config)
			for target in corpus.targets
			if target.type_path is not None
		}
		target_groups = {
			type_path: tuple(reasons)
			for type_path, reasons in target_group_reasons.items()
		}
		index = _ReviewCatalogIndex(
			target_by_type=target_by_type,
			visibility_by_type=visibility_by_type,
			target_group_reasons=target_group_reasons,
			target_groups=target_groups,
		)
		for cached_key in tuple(_REVIEW_CATALOG_INDEX_CACHE):
			if cached_key[0] == resolved_root:
				del _REVIEW_CATALOG_INDEX_CACHE[cached_key]
		_REVIEW_CATALOG_INDEX_CACHE[key] = index
		return index


def _entry_payload(entry: LoreEntry, target_by_type: dict[str, dict[str, object]], issues: list[dict[str, str]]) -> dict[str, object]:
	raw_data = thaw_json(entry.raw_data)
	target = target_by_type.get(entry.type_path or "", {})
	base_values = target.get("base_values")
	if not isinstance(base_values, dict):
		base_values = {}
	return {
		"id": entry.entry_id,
		"type_path": entry.type_path,
		"name": entry.name,
		"description": entry.description,
		"special_desc_requirement": entry.special_desc_requirement,
		"special_desc": entry.special_desc,
		"source_file": entry.source_path.as_posix(),
		"category": entry.source_path.stem,
		"field_profile": target.get("field_profile"),
		"label": target.get("label"),
		"base_name": base_values.get("name"),
		"base_description": base_values.get("description"),
		"icon_metadata": target.get("icon_metadata", {}),
		"raw": raw_data,
		"issues": issues,
	}


def _matches(
	entry: dict[str, object],
	query: str,
	category: str = "",
	groups: tuple[str, ...] = (),
	statuses: tuple[str, ...] = (),
) -> bool:
	if category and entry.get("category") != category:
		return False
	if groups and not set(groups).intersection(entry.get("groups", [])):
		return False
	if statuses and entry.get("status") not in statuses:
		return False
	if not query:
		return True
	needle = query.casefold()
	return needle in " ".join(
		str(entry.get(field) or "")
		for field in (
			"id",
			"type_path",
			"name",
			"description",
			"special_desc_requirement",
			"special_desc",
			"label",
			"base_name",
			"base_description",
			"editable_root",
			"parent_type",
			"group_labels",
			"suppression_reasons",
		)
	).casefold()


def list_entries_response(
	repo_root: Path,
	*,
	query: str = "",
	category: str = "",
	asset_root: Path | None = None,
) -> dict[str, object]:
	try:
		corpus = load_corpus(repo_root)
	except (OSError, ValueError) as exc:
		message = str(exc)
		path = message.split(": malformed JSON", 1)[0]
		return {
			"entries": [],
			"issues": [{"path": path, "message": message, "severity": "error"}],
		}

	all_issues = validate_corpus(repo_root, corpus, asset_root=asset_root)
	issues_by_entry: dict[str, list[dict[str, str]]] = {}
	for issue in all_issues:
		entry_key = issue.path.rsplit(".", 1)[0]
		issues_by_entry.setdefault(entry_key, []).append(_issue_payload(issue))

	target_by_type = _target_by_type(corpus)
	entries: list[dict[str, object]] = []
	ordered_entries = sorted(
		corpus.entries,
		key=lambda current: (current.type_path or "", current.source_path.as_posix(), current.entry_id or ""),
	)
	for entry in ordered_entries:
		entry_key = f"{entry.source_path.as_posix()}#{entry.entry_id or '<unknown>'}"
		payload = _entry_payload(entry, target_by_type, issues_by_entry.get(entry_key, []))
		if _matches(payload, query, category):
			entries.append(payload)
	return {"entries": entries, "issues": all_issues and [_issue_payload(issue) for issue in all_issues] or []}


def list_entries(
	repo_root: Path,
	*,
	query: str = "",
	category: str = "",
	asset_root: Path | None = None,
) -> list[dict[str, object]]:
	return list_entries_response(repo_root, query=query, category=category, asset_root=asset_root)["entries"]  # type: ignore[return-value]


def _catalog_review_payload(raw_target: dict[str, object]) -> dict[str, object]:
	base_values = raw_target.get("base_values")
	if not isinstance(base_values, dict):
		base_values = {}
	type_path = raw_target.get("type_path")
	return {
		"id": f"catalog:{type_path}",
		"type_path": type_path,
		"name": None,
		"description": None,
		"special_desc_requirement": None,
		"special_desc": None,
		"source_file": None,
		"category": "catalog",
		"field_profile": raw_target.get("field_profile"),
		"label": raw_target.get("label"),
		"editable_root": raw_target.get("editable_root"),
		"parent_type": raw_target.get("parent_type"),
		"base_name": base_values.get("name"),
		"base_description": base_values.get("description"),
		"icon_metadata": raw_target.get("icon_metadata", {}),
		"raw": None,
		"approved": False,
		"has_override": False,
		"status": "unreviewed",
		"issues": [],
	}


_DIRECTIONAL_SEGMENTS = frozenset(("directional", "north", "south", "east", "west", "left", "right"))


def _target_root(target: dict[str, object]) -> str:
	root = target.get("editable_root")
	if isinstance(root, str) and root.startswith("/"):
		return root
	type_path = target.get("type_path")
	return type_path if isinstance(type_path, str) else ""


def _target_visibility_metadata(targets: tuple[dict[str, object], ...]) -> dict[str, dict[str, object]]:
	duplicate_keys: dict[tuple[str, str, str], int] = {}
	for target in targets:
		base_values = target.get("base_values")
		if not isinstance(base_values, dict):
			continue
		name = base_values.get("name")
		description = base_values.get("description")
		if not isinstance(name, str) or not isinstance(description, str):
			continue
		key = (_target_root(target), name, description)
		duplicate_keys[key] = duplicate_keys.get(key, 0) + 1

	metadata: dict[str, dict[str, object]] = {}
	for target in targets:
		type_path = str(target.get("type_path") or "")
		segments = set(type_path.casefold().split("/"))
		is_directional = target.get("field_profile") == "atom_like" and bool(segments.intersection(_DIRECTIONAL_SEGMENTS))
		base_values = target.get("base_values")
		name = base_values.get("name") if isinstance(base_values, dict) else None
		description = base_values.get("description") if isinstance(base_values, dict) else None
		root = _target_root(target)
		is_redundant = (
			isinstance(name, str)
			and isinstance(description, str)
			and
			type_path != root
			and duplicate_keys.get((root, name, description), 0) > 1
		)
		reasons: list[str] = []
		if is_directional:
			reasons.append("directional")
		if is_redundant:
			reasons.append("redundant")
		metadata[type_path] = {
			"directional": is_directional,
			"redundant": is_redundant,
			"suppression_reasons": reasons,
		}
	return metadata


_ERE_SPECIAL_CHARACTERS = re.compile(r"([.*+?^${}()|\[\]\\])")


def find_type_definition(game_repo_root: Path, type_path: str) -> dict[str, object] | None:
	"""Best-effort search for the .dm source line that defines `type_path`.

	The catalog probe records only the type path and its scanned field values -- no source file or line
	is tracked anywhere -- so this searches the live game checkout directly via `git grep` for a `.dm`
	line consisting of exactly this type path. tgstation-style codebases almost always write each type's
	own definition on such a line, so this is reliable for the base/original definition; it does not
	distinguish that from a later reopen of the same type elsewhere, so the first match (git's own
	tree-order, which sorts before any modular_*/master_files override directories) is used. Returns
	None if no match is found.

	The trailing `\r?` tolerates CRLF line endings, which DM source on a Windows checkout almost always
	has -- `$` alone does not match before a literal trailing carriage return.
	"""
	if not type_path:
		return None
	escaped = _ERE_SPECIAL_CHARACTERS.sub(r"\\\1", type_path)
	matches = find_line_in_tracked_files(game_repo_root, f"^{escaped}\r?$", glob="*.dm")
	if not matches:
		return None
	return {"path": matches[0]["path"], "line": matches[0]["line"]}


def _group_payload(group: GroupRecord) -> dict[str, object]:
	return {
		"id": group.id,
		"label": group.label,
		"color": group.color,
		"keywords": list(group.keywords),
		"type_path_prefixes": list(group.type_path_prefixes),
		"keyword_scope": list(group.keyword_scope),
	}


def _review_payload(review: ReviewRecord | None) -> dict[str, object] | None:
	if review is None:
		return None
	return {
		"status": review.status,
		"reviewed_by": review.reviewed_by,
		"reviewed_at": review.reviewed_at,
		"notes": review.notes,
	}


def _decorate_review_item(
	entry: dict[str, object],
	*,
	type_path: str,
	group_ids: tuple[str, ...],
	group_match_reasons: dict[str, tuple[str, ...]],
	group_labels: dict[str, str],
	review: ReviewRecord | None,
	issues: list[dict[str, str]],
	visibility: dict[str, object],
) -> dict[str, object]:
	entry["groups"] = list(group_ids)
	entry["group_labels"] = [group_labels[group_id] for group_id in group_ids if group_id in group_labels]
	entry["group_match_reasons"] = {
		group_id: list(group_match_reasons[group_id])
		for group_id in group_ids
		if group_id in group_match_reasons
	}
	entry["review"] = _review_payload(review)
	entry["has_override"] = bool(entry.get("approved"))
	entry.update(visibility)
	entry["base_status"] = "overridden" if entry["has_override"] else ("reviewed" if review and review.status == "reviewed" else "unreviewed")
	if review and review.status == "needs-attention":
		entry["status"] = "needs-attention"
	else:
		entry["status"] = "needs-attention" if issues and review is None else entry["base_status"]
	entry["issues"] = issues
	entry["type_path"] = type_path
	return entry


def _sorted_review_entries(entries: list[dict[str, object]], sort: str) -> list[dict[str, object]]:
	if sort not in {"name", "type_path", "status", "reviewed_at"}:
		raise ValueError("Unsupported review sort. Choose name, type_path, status, or reviewed_at.")
	if sort == "name":
		return sorted(entries, key=lambda entry: (str(entry.get("name") or entry.get("base_name") or entry.get("label") or "").casefold(), str(entry.get("type_path") or "")))
	if sort == "status":
		order = {"needs-attention": 0, "unreviewed": 1, "reviewed": 2, "overridden": 3}
		return sorted(entries, key=lambda entry: (order.get(str(entry.get("status")), 99), str(entry.get("type_path") or "")))
	if sort == "reviewed_at":
		return sorted(entries, key=lambda entry: (str((entry.get("review") or {}).get("reviewed_at", "")), str(entry.get("type_path") or "")))
	return sorted(entries, key=lambda entry: str(entry.get("type_path") or ""))


def _reviews_stamp(repo_root: Path, layout: WorkspaceLayout) -> tuple[int, int]:
	if layout.standalone:
		return _tree_stamp(resolve_repo_path(repo_root, layout.content_reviews_root))
	return _file_stamp(resolve_repo_path(repo_root, layout.reviews_path))


@dataclass(frozen=True)
class _ReviewEntriesSnapshot:
	review_entries: tuple[dict[str, object], ...]
	status_counts: dict[str, int]
	group_counts: dict[str, int]
	catalog_count: int
	approved_count: int
	review_count: int
	groups_payload: tuple[dict[str, object], ...]
	issues_payload: tuple[dict[str, str], ...]


_REVIEW_ENTRIES_CACHE: dict[tuple[object, ...], _ReviewEntriesSnapshot] = {}
_REVIEW_ENTRIES_CACHE_LOCK = Lock()


def _build_review_entries_snapshot(
	repo_root: Path,
	corpus: LoreCorpus,
	group_config: GroupConfig,
	reviews: dict[str, ReviewRecord],
	*,
	asset_root: Path | None,
) -> _ReviewEntriesSnapshot:
	all_issues = validate_corpus(repo_root, corpus, asset_root=asset_root)
	issues_by_entry: dict[str, list[dict[str, str]]] = {}
	for issue in all_issues:
		entry_key = issue.path.rsplit(".", 1)[0]
		issues_by_entry.setdefault(entry_key, []).append(_issue_payload(issue))

	index = _review_catalog_index(repo_root, corpus, group_config)
	target_by_type = index.target_by_type
	visibility_by_type = index.visibility_by_type
	group_labels = {group.id: group.label for group in group_config.groups}
	target_group_reasons = index.target_group_reasons
	target_groups = index.target_groups
	approved_by_type: dict[str | None, list[dict[str, object]]] = {}
	for entry in sorted(
		corpus.entries,
		key=lambda current: (current.type_path or "", current.source_path.as_posix(), current.entry_id or ""),
	):
		entry_key = f"{entry.source_path.as_posix()}#{entry.entry_id or '<unknown>'}"
		payload = _entry_payload(entry, target_by_type, issues_by_entry.get(entry_key, []))
		payload["approved"] = True
		approved_by_type.setdefault(entry.type_path, []).append(payload)

	review_entries: list[dict[str, object]] = []
	seen_entry_ids: set[str] = set()
	for target in sorted(corpus.targets, key=lambda current: current.type_path or ""):
		type_path = target.type_path
		approved_entries = approved_by_type.get(type_path, [])
		if approved_entries:
			for approved_entry in approved_entries:
				review_entries.append(_decorate_review_item(
					approved_entry,
					type_path=type_path or "",
					group_ids=target_groups.get(type_path, ()),
					group_match_reasons=target_group_reasons.get(type_path, {}),
					group_labels=group_labels,
					review=reviews.get(type_path or ""),
					issues=approved_entry.get("issues", []),  # type: ignore[arg-type]
					visibility=visibility_by_type.get(type_path or "", {}),
				))
			seen_entry_ids.update(str(entry.get("id")) for entry in approved_entries if entry.get("id"))
			continue
		raw_target = target_by_type.get(type_path or "", {})
		catalog_entry = _catalog_review_payload(raw_target)
		review_entries.append(_decorate_review_item(
			catalog_entry,
			type_path=type_path or "",
			group_ids=target_groups.get(type_path, ()),
			group_match_reasons=target_group_reasons.get(type_path, {}),
			group_labels=group_labels,
			review=reviews.get(type_path or ""),
			issues=[],
			visibility=visibility_by_type.get(type_path or "", {}),
		))

	for entry_list in approved_by_type.values():
		for entry in entry_list:
			entry_id = entry.get("id")
			if entry_id and str(entry_id) not in seen_entry_ids:
				entry_type_path = str(entry.get("type_path") or "")
				review_entries.append(_decorate_review_item(
					entry,
					type_path=entry_type_path,
					group_ids=target_groups.get(entry_type_path, ()),
					group_match_reasons=target_group_reasons.get(entry_type_path, {}),
					group_labels=group_labels,
					review=reviews.get(entry_type_path),
					issues=entry.get("issues", []),  # type: ignore[arg-type]
					visibility=visibility_by_type.get(entry_type_path, {}),
				))

	status_counts: dict[str, int] = {}
	group_counts: dict[str, int] = {}
	for entry in review_entries:
		status = str(entry.get("status"))
		status_counts[status] = status_counts.get(status, 0) + 1
		for group_id in entry.get("groups", []):
			group_counts[str(group_id)] = group_counts.get(str(group_id), 0) + 1

	return _ReviewEntriesSnapshot(
		review_entries=tuple(review_entries),
		status_counts=status_counts,
		group_counts=group_counts,
		catalog_count=len(corpus.targets),
		approved_count=len(corpus.entries),
		review_count=len(reviews),
		groups_payload=tuple(_group_payload(group) for group in group_config.groups),
		issues_payload=tuple(_issue_payload(issue) for issue in all_issues),
	)


def _review_entries_snapshot(
	repo_root: Path,
	corpus: LoreCorpus,
	group_config: GroupConfig,
	reviews: dict[str, ReviewRecord],
	*,
	asset_root: Path | None,
) -> _ReviewEntriesSnapshot:
	resolved_root = repo_root.resolve()
	resolved_asset_root = (asset_root or repo_root).resolve()
	layout = WorkspaceLayout.from_root(resolved_root)
	key = (
		resolved_root,
		resolved_asset_root,
		_file_stamp(resolve_repo_path(resolved_root, layout.targets_path)),
		_tree_stamp(resolve_repo_path(resolved_root, layout.content_groups_root if layout.standalone else layout.groups_path)),
		_tree_stamp(resolve_repo_path(resolved_root, layout.content_assignments_root)) if layout.standalone else (0, 0),
		_reviews_stamp(resolved_root, layout),
		_tree_stamp(resolve_repo_path(resolved_root, layout.entities_root)),
	)
	with _REVIEW_ENTRIES_CACHE_LOCK:
		cached_snapshot = _REVIEW_ENTRIES_CACHE.get(key)
		if cached_snapshot is not None:
			return cached_snapshot

		snapshot = _build_review_entries_snapshot(resolved_root, corpus, group_config, reviews, asset_root=asset_root)
		for cached_key in tuple(_REVIEW_ENTRIES_CACHE):
			if cached_key[0] == resolved_root:
				del _REVIEW_ENTRIES_CACHE[cached_key]
		_REVIEW_ENTRIES_CACHE[key] = snapshot
		return snapshot


def list_review_response(
	repo_root: Path,
	*,
	query: str = "",
	category: str = "",
	groups: tuple[str, ...] = (),
	statuses: tuple[str, ...] = (),
	sort: str = "name",
	include_directional: bool = False,
	include_redundant: bool = False,
	offset: int = 0,
	limit: int | None = None,
	asset_root: Path | None = None,
) -> dict[str, object]:
	if offset < 0:
		raise ValueError("Review offset must not be negative.")
	if limit is not None and limit < 1:
		raise ValueError("Review limit must be positive.")
	try:
		corpus = load_corpus(repo_root)
		group_config = load_groups(repo_root)
		reviews = load_reviews(repo_root)
	except (OSError, ValueError) as exc:
		message = str(exc)
		path = message.split(": malformed JSON", 1)[0]
		return {
			"entries": [],
			"catalog_count": 0,
			"approved_count": 0,
			"status_counts": {},
			"group_counts": {},
			"issues": [{"path": path, "message": message, "severity": "error"}],
		}

	snapshot = _review_entries_snapshot(repo_root, corpus, group_config, reviews, asset_root=asset_root)
	review_entries = snapshot.review_entries

	visible_entries = [
		entry for entry in review_entries
		if (include_directional or not entry.get("directional"))
		and (include_redundant or not entry.get("redundant"))
	]
	filtered_entries = [entry for entry in visible_entries if _matches(entry, query, category, groups, statuses)]
	sorted_entries = _sorted_review_entries(filtered_entries, sort)
	page_entries = sorted_entries[offset:] if limit is None else sorted_entries[offset:offset + limit]
	suppressed_counts = {
		"directional": sum(1 for entry in review_entries if entry.get("directional") and not include_directional),
		"redundant": sum(1 for entry in review_entries if entry.get("redundant") and not include_redundant),
	}
	return {
		"entries": page_entries,
		"matched_entry_count": len(sorted_entries),
		"returned_entry_count": len(page_entries),
		"has_more": offset + len(page_entries) < len(sorted_entries),
		"offset": offset,
		"limit": limit,
		"catalog_count": snapshot.catalog_count,
		"approved_count": snapshot.approved_count,
		"review_count": snapshot.review_count,
		"status_counts": snapshot.status_counts,
		"group_counts": snapshot.group_counts,
		"visible_entry_count": len(visible_entries),
		"visible_catalog_count": sum(1 for entry in visible_entries if not entry.get("has_override")),
		"suppressed_counts": suppressed_counts,
		"groups": list(snapshot.groups_payload),
		"issues": list(snapshot.issues_payload),
	}


def groups_response(repo_root: Path) -> dict[str, object]:
	corpus = load_corpus(repo_root)
	group_config = load_groups(repo_root)
	index = _review_catalog_index(repo_root, corpus, group_config)
	approved_counts: dict[str, int] = {}
	for entry in corpus.entries:
		if entry.type_path is not None:
			approved_counts[entry.type_path] = approved_counts.get(entry.type_path, 0) + 1
	group_counts: dict[str, int] = {}
	for type_path, group_ids in index.target_groups.items():
		entry_count = approved_counts.get(type_path, 0) or 1
		for group_id in group_ids:
			group_counts[group_id] = group_counts.get(group_id, 0) + entry_count
	return {
		"groups": [
			{**_group_payload(group), "count": group_counts.get(group.id, 0)}
			for group in group_config.groups
		],
		"assignments": {type_path: list(group_ids) for type_path, group_ids in group_config.assignments.items()},
		"counts": group_counts,
	}


def save_group_response(repo_root: Path, payload: object) -> dict[str, object]:
	if not isinstance(payload, dict):
		raise ValueError("Group payload must be a JSON object.")
	for field_name in ("id", "label", "color"):
		if not isinstance(payload.get(field_name), str):
			raise ValueError(f"Group payload requires a string {field_name}.")
	for field_name in ("keywords", "type_path_prefixes", "keyword_scope"):
		if field_name not in payload:
			continue
		field_value = payload[field_name]
		if not isinstance(field_value, list) or any(not isinstance(value, str) for value in field_value):
			raise ValueError(f"Group payload {field_name} must be an array of strings.")
	group = GroupRecord(
		id=payload["id"],
		label=payload["label"],
		color=payload["color"],
		keywords=tuple(payload.get("keywords", [])),
		type_path_prefixes=tuple(payload.get("type_path_prefixes", [])),
		keyword_scope=tuple(payload["keyword_scope"]) if "keyword_scope" in payload else DEFAULT_KEYWORD_SCOPE,
	)
	save_group(repo_root, group)
	assignments = payload.get("assignments", [])
	if not isinstance(assignments, list) or any(not isinstance(type_path, str) for type_path in assignments):
		raise ValueError("Group assignments must be an array of type paths.")
	for type_path in assignments:
		current = load_groups(repo_root).assignments.get(type_path, ())
		updated = tuple(group.id if existing != group.id else existing for existing in current)
		if group.id not in updated:
			updated += (group.id,)
		save_group_assignments(repo_root, type_path, updated)
	return {"group": _group_payload(group), "issues": []}


def save_review_response(repo_root: Path, type_path: str, payload: object) -> dict[str, object]:
	if not type_path.startswith("/"):
		raise ValueError("Review type paths must be absolute.")
	if payload is None or (isinstance(payload, dict) and payload.get("status") in (None, "")):
		save_review(repo_root, type_path, None)
		return {"review": None, "issues": []}
	if not isinstance(payload, dict) or payload.get("status") not in REVIEW_STATUSES:
		raise ValueError("Review payload status must be 'reviewed', 'needs-attention', or null.")
	reviewed_by = payload.get("reviewed_by")
	if not isinstance(reviewed_by, str) or not reviewed_by.strip():
		raise ValueError("Review payload requires reviewed_by.")
	record = ReviewRecord(
		status=payload["status"],
		reviewed_by=reviewed_by.strip(),
		reviewed_at=datetime.now(timezone.utc).isoformat(),
		notes=payload.get("notes", "") if isinstance(payload.get("notes", ""), str) else "",
	)
	save_review(repo_root, type_path, record)
	return {"review": _review_payload(record), "issues": []}


def catalog_response(repo_root: Path) -> dict[str, object]:
	return {
		"targets": list_catalog(repo_root),
		"generated_at": datetime.now(timezone.utc).isoformat(),
		"standalone": WorkspaceLayout.from_root(repo_root).standalone,
	}


def _resolve_entity_source(repo_root: Path, source_file: str, *, allow_missing: bool = False) -> Path:
	relative_path = Path(source_file)
	if relative_path.is_absolute():
		raise ValueError("Source files must use repository-relative paths.")
	resolved_path = resolve_repo_path(repo_root, relative_path)
	layout = WorkspaceLayout.from_root(repo_root)
	entities_root = resolve_repo_path(repo_root, layout.entities_root)
	if not resolved_path.is_relative_to(entities_root) or resolved_path.suffix.casefold() != ".json":
		raise ValueError("Source files must be JSON files inside the configured lore override directory.")
	if not allow_missing and not resolved_path.is_file():
		raise ValueError(f"Source file '{relative_path.as_posix()}' does not exist.")
	return resolved_path.relative_to(repo_root.resolve())


def list_entity_files(repo_root: Path) -> list[str]:
	return [path.as_posix() for path in iter_entity_paths(repo_root)]


def _replace_raw_entry(document: object, entry_id: str, replacement: dict[str, object]) -> object:
	if isinstance(document, list):
		updated_document = list(document)
		for index, raw_entry in enumerate(updated_document):
			if isinstance(raw_entry, dict) and raw_entry.get("id") == entry_id:
				updated_document[index] = replacement
				return updated_document
		raise ValueError(f"Lore entry '{entry_id}' was not found in its source file.")
	if isinstance(document, dict) and document.get("id") == entry_id:
		return replacement
	raise ValueError(f"Lore entry '{entry_id}' was not found in its source file.")


def _candidate_corpus(repo_root: Path, source_path: Path, entry_id: str, raw_entry: object) -> LoreCorpus:
	if not isinstance(raw_entry, dict):
		raise ValueError("Lore entry must be a JSON object.")
	corpus = load_corpus(repo_root)
	candidate_entry = make_lore_entry(source_path, raw_entry)
	entries: list[LoreEntry] = []
	replaced = False
	for existing_entry in corpus.entries:
		if existing_entry.source_path == source_path and existing_entry.entry_id == entry_id:
			entries.append(candidate_entry)
			replaced = True
		else:
			entries.append(existing_entry)
	if not replaced:
		if any(existing_entry.entry_id == entry_id for existing_entry in corpus.entries):
			raise ValueError(f"Lore entry '{entry_id}' belongs to a different source file.")
		entries.append(candidate_entry)
	return LoreCorpus(targets=corpus.targets, entries=tuple(entries))


def _format_issues(issues: list[ValidationIssue]) -> str:
	return "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)


def validate_entry(
	repo_root: Path,
	*,
	source_file: str,
	entry: object,
	asset_root: Path | None = None,
) -> dict[str, object]:
	if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
		raise ValueError("Lore entry must contain a string id.")
	resolved_root = repo_root.resolve()
	source_path = _resolve_entity_source(resolved_root, source_file)
	candidate = _candidate_corpus(resolved_root, source_path, entry["id"], entry)
	issues = validate_corpus(resolved_root, candidate, asset_root=asset_root)
	return {"valid": not issues, "issues": [_issue_payload(issue) for issue in issues]}


def validate_entries(
	repo_root: Path,
	*,
	entries: list[object],
	source_file: str | None = None,
	asset_root: Path | None = None,
) -> dict[str, object]:
	resolved_root = repo_root.resolve()
	corpus = load_corpus(resolved_root)
	if entries:
		candidate_entries = list(corpus.entries)
		for raw_entry in entries:
			if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("id"), str):
				raise ValueError("Each lore entry must contain a string id.")
			entry_id = raw_entry["id"]
			if source_file is not None:
				source_path = _resolve_entity_source(resolved_root, source_file)
			else:
				matching_entries = [entry for entry in corpus.entries if entry.entry_id == entry_id]
				if not matching_entries:
					raise ValueError(f"Lore entry '{entry_id}' was not found in the current corpus.")
				source_path = matching_entries[0].source_path
			candidate_entry = make_lore_entry(source_path, raw_entry)
			replaced = False
			for index, existing_entry in enumerate(candidate_entries):
				if existing_entry.entry_id == entry_id:
					candidate_entries[index] = candidate_entry
					replaced = True
					break
			if not replaced:
				candidate_entries.append(candidate_entry)
		corpus = LoreCorpus(targets=corpus.targets, entries=tuple(candidate_entries))
	issues = validate_corpus(resolved_root, corpus, asset_root=asset_root)
	return {"valid": not issues, "issues": [_issue_payload(issue) for issue in issues]}


def _atomic_write(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
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


def create_entry(
	repo_root: Path,
	*,
	source_file: str,
	entry: object,
	asset_root: Path | None = None,
) -> dict[str, object]:
	if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
		raise ValueError("New lore entry must contain a string id.")
	resolved_root = repo_root.resolve()
	source_path = _resolve_entity_source(resolved_root, source_file, allow_missing=True)
	original_source_path = resolved_root / source_path
	original_source_exists = original_source_path.exists()
	original_source_bytes = original_source_path.read_bytes() if original_source_exists else None
	layout = WorkspaceLayout.from_root(resolved_root)
	if layout.standalone:
		if original_source_exists:
			raise ValueError(f"Lore entry source file '{source_file}' already exists.")
		updated_document = entry
	elif original_source_exists:
		original_document = read_json_file(resolved_root, source_path)
		if not isinstance(original_document, list):
			raise ValueError("New overrides can only be added to JSON array entity groups.")
		if any(isinstance(raw_entry, dict) and raw_entry.get("id") == entry["id"] for raw_entry in original_document):
			raise ValueError(f"Lore entry '{entry['id']}' already exists in its entity group.")
		updated_document = [*original_document, entry]
	else:
		updated_document = [entry]
	candidate = _candidate_corpus(resolved_root, source_path, entry["id"], entry)
	issues = validate_corpus(resolved_root, candidate, asset_root=asset_root)
	if issues:
		raise ValueError(f"Lore corpus validation failed:\n{_format_issues(issues)}")

	generated_path = resolved_root / layout.generated_dm_path
	original_generated_exists = generated_path.exists()
	original_generated_bytes = generated_path.read_bytes() if original_generated_exists else None
	serialized_document = (json.dumps(updated_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
	try:
		_atomic_write(original_source_path, serialized_document)
		write_generated_dm(resolved_root)
	except Exception:
		if original_source_exists and original_source_bytes is not None:
			_atomic_write(original_source_path, original_source_bytes)
		elif original_source_path.exists():
			original_source_path.unlink()
		if original_generated_exists and original_generated_bytes is not None:
			_atomic_write(generated_path, original_generated_bytes)
		elif generated_path.exists():
			generated_path.unlink()
		raise

	for saved_entry in list_entries_response(resolved_root, asset_root=asset_root)["entries"]:
		if isinstance(saved_entry, dict) and saved_entry.get("id") == entry["id"]:
			return saved_entry
	raise ValueError(f"Created lore entry '{entry['id']}' could not be reloaded.")


def save_entry(
	repo_root: Path,
	*,
	entry_id: str,
	source_file: str,
	entry: object,
	asset_root: Path | None = None,
) -> dict[str, object]:
	if not isinstance(entry, dict):
		raise ValueError("Lore entry must be a JSON object.")
	if entry.get("id") != entry_id:
		raise ValueError("The route entry id must match entry.id.")

	resolved_root = repo_root.resolve()
	layout = WorkspaceLayout.from_root(resolved_root)
	source_path = _resolve_entity_source(resolved_root, source_file)
	original_source_path = resolved_root / source_path
	original_source_bytes = original_source_path.read_bytes()
	original_document = read_json_file(resolved_root, source_path)
	try:
		updated_document = _replace_raw_entry(original_document, entry_id, entry)
	except ValueError:
		if not isinstance(original_document, list):
			raise
		updated_document = [*original_document, entry]
	candidate = _candidate_corpus(resolved_root, source_path, entry_id, entry)
	issues = validate_corpus(resolved_root, candidate, asset_root=asset_root)
	if issues:
		raise ValueError(f"Lore corpus validation failed:\n{_format_issues(issues)}")

	generated_path = resolved_root / layout.generated_dm_path
	original_generated_exists = generated_path.exists()
	original_generated_bytes = generated_path.read_bytes() if original_generated_exists else None
	serialized_document = (json.dumps(updated_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
	try:
		_atomic_write(original_source_path, serialized_document)
		write_generated_dm(resolved_root)
	except Exception:
		_atomic_write(original_source_path, original_source_bytes)
		if original_generated_exists and original_generated_bytes is not None:
			_atomic_write(generated_path, original_generated_bytes)
		elif generated_path.exists():
			generated_path.unlink()
		raise

	response = list_entries_response(resolved_root, asset_root=asset_root)
	for saved_entry in response["entries"]:
		if isinstance(saved_entry, dict) and saved_entry.get("id") == entry_id:
			return saved_entry
	raise ValueError(f"Saved lore entry '{entry_id}' could not be reloaded.")


def delete_entry(
	repo_root: Path,
	*,
	entry_id: str,
	source_file: str,
) -> dict[str, object]:
	resolved_root = repo_root.resolve()
	layout = WorkspaceLayout.from_root(resolved_root)
	source_path = _resolve_entity_source(resolved_root, source_file)
	original_source_path = resolved_root / source_path
	original_source_bytes = original_source_path.read_bytes()
	original_document = read_json_file(resolved_root, source_path)

	if isinstance(original_document, list):
		remaining_document = [
			raw_entry for raw_entry in original_document
			if not (isinstance(raw_entry, dict) and raw_entry.get("id") == entry_id)
		]
		if len(remaining_document) == len(original_document):
			raise ValueError(f"Lore entry '{entry_id}' was not found in its source file.")
	elif isinstance(original_document, dict) and original_document.get("id") == entry_id:
		remaining_document = None
	else:
		raise ValueError(f"Lore entry '{entry_id}' was not found in its source file.")

	generated_path = resolved_root / layout.generated_dm_path
	original_generated_exists = generated_path.exists()
	original_generated_bytes = generated_path.read_bytes() if original_generated_exists else None
	try:
		if remaining_document:
			serialized_document = (json.dumps(remaining_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
			_atomic_write(original_source_path, serialized_document)
		else:
			original_source_path.unlink()
		write_generated_dm(resolved_root)
	except Exception:
		_atomic_write(original_source_path, original_source_bytes)
		if original_generated_exists and original_generated_bytes is not None:
			_atomic_write(generated_path, original_generated_bytes)
		elif generated_path.exists():
			generated_path.unlink()
		raise

	return {"deleted": True, "id": entry_id}


def generate_output(repo_root: Path) -> dict[str, object]:
	generated_path = repo_root.resolve() / WorkspaceLayout.from_root(repo_root).generated_dm_path
	original_bytes = generated_path.read_bytes() if generated_path.exists() else None
	write_generated_dm(repo_root.resolve())
	return {
		"generated": True,
		"changed": generated_path.read_bytes() != original_bytes,
		"issues": [],
	}
