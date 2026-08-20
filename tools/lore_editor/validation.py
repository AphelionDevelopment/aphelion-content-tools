from __future__ import annotations

import re
from pathlib import Path

from tools.dmi import Dmi

from .model import (
	FrozenJson,
	LoreCorpus,
	LoreEntry,
	SUPPORTED_ICON_KEYS,
	SUPPORTED_SPECIAL_DESC_REQUIREMENTS,
	ValidationIssue,
	as_object,
	as_string,
)
from .source import resolve_repo_path

TYPE_PATH_PATTERN = re.compile(r"^/(?:[A-Za-z0-9_]+)(?:/[A-Za-z0-9_]+)*$")
WIKI_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SUPPORTED_TOP_LEVEL_KEYS = {
	"id",
	"type_path",
	"name",
	"description",
	"special_desc_requirement",
	"special_desc",
	"icons",
	"wiki",
}
ICON_FIELD_ORDER = tuple(SUPPORTED_ICON_KEYS)
WIKI_FIELD_ORDER = ("enabled", "slug", "summary", "export_icon")
ICON_RECORD_KEYS = {"file", "state"}
TARGETS_PATH_TEXT = "config/aphelion/lore_overhaul/targets.json"


def issue_path(entry: LoreEntry, field: str) -> str:
    entry_id = entry.entry_id if entry.entry_id else "<unknown>"
    return f"{entry.source_path.as_posix()}#{entry_id}.{field}"


def make_issue(entry: LoreEntry, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(path=issue_path(entry, field), message=message, severity="error")


def resolve_icon_path(repo_root: Path, icon_file: str, *, asset_root: Path | None = None) -> Path | None:
	try:
		return resolve_repo_path(asset_root or repo_root, Path(icon_file))
	except ValueError:
		return None


def validate_entry_shape(entry: LoreEntry, issues: list[ValidationIssue]) -> None:
    raw_object = as_object(entry.raw_data)
    if raw_object is None:
        issues.append(make_issue(entry, "entry", "Lore entry must be a JSON object."))
        return

    for key in sorted(set(raw_object) - SUPPORTED_TOP_LEVEL_KEYS):
        issues.append(make_issue(entry, key, f"Unsupported top-level field '{key}'."))

    raw_id = raw_object.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        issues.append(make_issue(entry, "id", "Field 'id' must be a non-empty string."))

    raw_type_path = raw_object.get("type_path")
    if not isinstance(raw_type_path, str) or not raw_type_path:
        issues.append(make_issue(entry, "type_path", "Field 'type_path' must be a non-empty string."))
    elif not TYPE_PATH_PATTERN.fullmatch(raw_type_path):
        issues.append(
            make_issue(
                entry,
                "type_path",
				"Type path must be an absolute BYOND path with identifier segments.",
            )
        )

    for field_name in ("name", "description", "special_desc"):
        if field_name in raw_object and not isinstance(raw_object[field_name], str):
            issues.append(make_issue(entry, field_name, f"Field '{field_name}' must be a string."))

    if "special_desc_requirement" in raw_object:
        requirement = raw_object["special_desc_requirement"]
        if not isinstance(requirement, str):
            issues.append(make_issue(entry, "special_desc_requirement", "Field 'special_desc_requirement' must be a string."))
        elif requirement not in SUPPORTED_SPECIAL_DESC_REQUIREMENTS:
            allowed_values = ", ".join(SUPPORTED_SPECIAL_DESC_REQUIREMENTS)
            issues.append(
                make_issue(
                    entry,
                    "special_desc_requirement",
                    f"Special description requirement must be one of {allowed_values}.",
                )
            )

    validate_icons(entry, raw_object.get("icons"), issues)
    validate_wiki(entry, raw_object.get("wiki"), issues)
    if entry.wiki is not None and entry.wiki.export_icon is True and not any(icon.key == "icon" for icon in entry.icons):
        issues.append(make_issue(entry, "wiki.export_icon", "AutoWiki icon export requires an 'icons.icon' record."))


def validate_icons(entry: LoreEntry, raw_icons: FrozenJson | None, issues: list[ValidationIssue]) -> None:
    if raw_icons is None:
        return
    icon_object = as_object(raw_icons)
    if icon_object is None:
        issues.append(make_issue(entry, "icons", "Field 'icons' must be an object."))
        return

    for key in sorted(icon_object):
        if key not in SUPPORTED_ICON_KEYS:
            issues.append(make_issue(entry, f"icons.{key}", f"Unsupported icon key '{key}'."))
            continue

        raw_icon_record = as_object(icon_object.get(key))
        if raw_icon_record is None:
            issues.append(make_issue(entry, f"icons.{key}", f"Icon record '{key}' must be an object."))
            continue

        for nested_key in sorted(set(raw_icon_record) - ICON_RECORD_KEYS):
            issues.append(make_issue(entry, f"icons.{key}.{nested_key}", f"Unsupported field '{nested_key}'."))

        raw_file = raw_icon_record.get("file")
        if not isinstance(raw_file, str) or not raw_file:
            issues.append(make_issue(entry, f"icons.{key}.file", "Field 'file' must be a non-empty string."))

        raw_state = raw_icon_record.get("state")
        if not isinstance(raw_state, str) or not raw_state:
            issues.append(make_issue(entry, f"icons.{key}.state", "Field 'state' must be a non-empty string."))


def validate_wiki(entry: LoreEntry, raw_wiki: FrozenJson | None, issues: list[ValidationIssue]) -> None:
    if raw_wiki is None:
        return
    wiki_object = as_object(raw_wiki)
    if wiki_object is None:
        issues.append(make_issue(entry, "wiki", "Field 'wiki' must be an object."))
        return

    for field_name in sorted(set(wiki_object) - set(WIKI_FIELD_ORDER)):
        issues.append(make_issue(entry, f"wiki.{field_name}", f"Unsupported field '{field_name}'."))

    for field_name in WIKI_FIELD_ORDER:
        if field_name not in wiki_object:
            issues.append(make_issue(entry, f"wiki.{field_name}", f"Field '{field_name}' is required."))

    if "enabled" in wiki_object and not isinstance(wiki_object["enabled"], bool):
        issues.append(make_issue(entry, "wiki.enabled", "Field 'enabled' must be a boolean."))

    raw_slug = wiki_object.get("slug")
    if "slug" in wiki_object and not isinstance(raw_slug, str):
        issues.append(make_issue(entry, "wiki.slug", "Field 'slug' must be a string."))
    elif isinstance(raw_slug, str) and not WIKI_SLUG_PATTERN.fullmatch(raw_slug):
        issues.append(make_issue(entry, "wiki.slug", "Wiki slug must match ^[a-z0-9]+(?:-[a-z0-9]+)*$."))

    if "summary" in wiki_object and not isinstance(wiki_object["summary"], str):
        issues.append(make_issue(entry, "wiki.summary", "Field 'summary' must be a string."))

    if "export_icon" in wiki_object and not isinstance(wiki_object["export_icon"], bool):
        issues.append(make_issue(entry, "wiki.export_icon", "Field 'export_icon' must be a boolean."))


def validate_icon_assets(
	repo_root: Path,
	entry: LoreEntry,
	issues: list[ValidationIssue],
	*,
	asset_root: Path | None = None,
) -> None:
    raw_object = as_object(entry.raw_data)
    if raw_object is None:
        return
    icon_object = as_object(raw_object.get("icons"))
    if icon_object is None:
        return

    for key in ICON_FIELD_ORDER:
        raw_icon_record = as_object(icon_object.get(key))
        if raw_icon_record is None:
            continue
        icon_file = as_string(raw_icon_record.get("file"))
        icon_state = as_string(raw_icon_record.get("state"))
        if icon_file is None or icon_state is None:
            continue

        resolved_icon_path = resolve_icon_path(repo_root, icon_file, asset_root=asset_root)
        if resolved_icon_path is None:
            issues.append(
                make_issue(
                    entry,
                    f"icons.{key}.file",
                    f"Icon file '{icon_file}' must stay within the repository root.",
                )
            )
            continue
        if not resolved_icon_path.exists():
            issues.append(make_issue(entry, f"icons.{key}.file", f"Icon file '{icon_file}' does not exist."))
            continue

        try:
            dmi = Dmi.from_file(resolved_icon_path)
        except Exception as exc:  # pragma: no cover - defensive path for unexpected asset failures
            issues.append(
                make_issue(
                    entry,
                    f"icons.{key}.file",
                    f"Icon file '{icon_file}' could not be read: {exc}.",
                )
            )
            continue

        try:
            dmi.get_state(icon_state)
        except KeyError:
            issues.append(
                make_issue(
                    entry,
                    f"icons.{key}.state",
                    f"Icon state '{icon_state}' was not found in {icon_file}.",
                )
            )


def iter_owned_fields(entry: LoreEntry) -> tuple[str, ...]:
    raw_object = as_object(entry.raw_data)
    if raw_object is None:
        return ()

    owned_fields: list[str] = []
    for field_name in ("name", "description", "special_desc_requirement", "special_desc"):
        if field_name in raw_object:
            owned_fields.append(field_name)

    icon_object = as_object(raw_object.get("icons"))
    if icon_object is not None:
        for key in ICON_FIELD_ORDER:
            if key in icon_object:
                owned_fields.append(f"icons.{key}")

    wiki_object = as_object(raw_object.get("wiki"))
    if wiki_object is not None:
        for field_name in WIKI_FIELD_ORDER:
            if field_name in wiki_object:
                owned_fields.append(f"wiki.{field_name}")

    return tuple(owned_fields)


def validate_duplicate_entry_ids(corpus: LoreCorpus, issues: list[ValidationIssue]) -> None:
    seen_ids: dict[str, LoreEntry] = {}
    for entry in corpus.entries:
        if not entry.entry_id:
            continue
        existing_entry = seen_ids.get(entry.entry_id)
        if existing_entry is None:
            seen_ids[entry.entry_id] = entry
            continue
        issues.append(
            make_issue(
                entry,
                "id",
                f"Duplicate lore entry id '{entry.entry_id}'; first defined in {existing_entry.source_path.as_posix()}.",
            )
        )


def validate_duplicate_field_ownership(corpus: LoreCorpus, issues: list[ValidationIssue]) -> None:
    owners: dict[tuple[str, str], str] = {}
    for entry in corpus.entries:
        if not entry.type_path or not TYPE_PATH_PATTERN.fullmatch(entry.type_path):
            continue
        for field_name in iter_owned_fields(entry):
            owner_key = (entry.type_path, field_name)
            existing_owner = owners.get(owner_key)
            current_owner = issue_path(entry, field_name)
            if existing_owner is None:
                owners[owner_key] = current_owner
                continue
            issues.append(
                make_issue(
                    entry,
                    field_name,
                    f"Target field '{field_name}' for {entry.type_path} is already owned by {existing_owner}.",
                )
                )


def validate_duplicate_wiki_slugs(corpus: LoreCorpus, issues: list[ValidationIssue]) -> None:
    seen_slugs: dict[str, LoreEntry] = {}
    for entry in corpus.entries:
        if entry.wiki is None or entry.wiki.enabled is not True or not entry.wiki.slug:
            continue
        existing_entry = seen_slugs.get(entry.wiki.slug)
        if existing_entry is None:
            seen_slugs[entry.wiki.slug] = entry
            continue
        issues.append(
            make_issue(
                entry,
                "wiki.slug",
                f"Duplicate AutoWiki slug '{entry.wiki.slug}'; first defined in {issue_path(existing_entry, 'wiki.slug').removesuffix('.wiki.slug')}.",
            )
        )


def validate_field_profiles(corpus: LoreCorpus, issues: list[ValidationIssue]) -> None:
	profile_by_type = {
		target.type_path: target.field_profile
		for target in corpus.targets
		if target.type_path is not None
	}
	for entry in corpus.entries:
		if profile_by_type.get(entry.type_path) == "named_datum":
			raw_object = as_object(entry.raw_data)
			if raw_object is not None:
				for field_name in ("special_desc_requirement", "special_desc"):
					if field_name in raw_object:
						issues.append(
							make_issue(
								entry,
								field_name,
								"Field profile 'named_datum' does not support special description overrides.",
							)
						)
		if not entry.icons or profile_by_type.get(entry.type_path) != "named_datum":
			continue
		issues.append(make_issue(entry, "icons", "Field profile 'named_datum' does not support icon overrides."))


def validate_catalog_membership(corpus: LoreCorpus, issues: list[ValidationIssue]) -> None:
    valid_type_paths = {
        target.type_path
        for target in corpus.targets
        if isinstance(target.type_path, str) and TYPE_PATH_PATTERN.fullmatch(target.type_path)
    }
    for entry in corpus.entries:
        if not entry.type_path or not TYPE_PATH_PATTERN.fullmatch(entry.type_path):
            continue
        if entry.type_path in valid_type_paths:
            continue
        issues.append(
            make_issue(
                entry,
                "type_path",
                f"Type path '{entry.type_path}' is not present in {TARGETS_PATH_TEXT}.",
            )
        )


def validate_corpus(repo_root: Path, corpus: LoreCorpus, *, asset_root: Path | None = None) -> list[ValidationIssue]:
    resolved_root = repo_root.resolve()
    issues: list[ValidationIssue] = []

    for entry in corpus.entries:
        validate_entry_shape(entry, issues)
        validate_icon_assets(resolved_root, entry, issues, asset_root=asset_root)

    validate_catalog_membership(corpus, issues)
    validate_field_profiles(corpus, issues)
    validate_duplicate_entry_ids(corpus, issues)
    validate_duplicate_field_ownership(corpus, issues)
    validate_duplicate_wiki_slugs(corpus, issues)
    return issues
