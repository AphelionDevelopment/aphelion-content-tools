from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .model import IconRecord, LoreCorpus, LoreEntry
from .source import load_corpus
from .validation import validate_corpus
from .workspace import WorkspaceLayout

GENERATED_DM_PATH = Path("modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm")
GENERATED_HEADER = (
	"/// THIS FILE IS GENERATED. DO NOT EDIT BY HAND.\n"
	"/// Source: config/aphelion/lore_overhaul\n"
)
ENTRY_ID_SEGMENT_PATTERN = re.compile(r"[^a-z0-9]+")
SPECIAL_DESC_REQUIREMENT_CONSTANTS = {
	"none": "EXAMINE_CHECK_NONE",
	"syndicate": "EXAMINE_CHECK_SYNDICATE",
	"syndicate_toy": "EXAMINE_CHECK_SYNDICATE_TOY",
	"mindshield": "EXAMINE_CHECK_MINDSHIELD",
	"role": "EXAMINE_CHECK_ROLE",
	"job": "EXAMINE_CHECK_JOB",
	"faction": "EXAMINE_CHECK_FACTION",
	"contractor": "EXAMINE_CHECK_CONTRACTOR",
}


def escape_dm_string(value: str) -> str:
	return (
		value.replace("\\", "\\\\")
		.replace('"', '\\"')
		.replace("\r", "\\r")
		.replace("\n", "\\n")
		.replace("\t", "\\t")
	)


def format_dm_string(value: str) -> str:
	return f'"{escape_dm_string(value)}"'


def format_dm_icon_path(value: str) -> str:
	return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def sort_entries(entries: tuple[LoreEntry, ...]) -> tuple[LoreEntry, ...]:
	return tuple(
		sorted(
			entries,
			key=lambda entry: (
				entry.source_path.as_posix(),
				entry.entry_id or "",
			),
		)
	)


def make_registry_subtype_name(entry_id: str | None) -> str:
	if not entry_id:
		return "unknown_entry"
	normalized_entry_id = ENTRY_ID_SEGMENT_PATTERN.sub("_", entry_id)
	normalized_entry_id = normalized_entry_id.strip("_")
	if not normalized_entry_id:
		return "unknown_entry"
	return normalized_entry_id


def autowiki_type_name(entry: LoreEntry) -> str:
	"""Return the generated AutoWiki subtype name for an enabled lore entry."""
	return make_registry_subtype_name(entry.entry_id)


def format_entry_diagnostic(entry: LoreEntry) -> str:
	entry_id = entry.entry_id if entry.entry_id else "<unknown>"
	return f"{entry.source_path.as_posix()}#{entry_id}"


def iter_registry_entries(entries: tuple[LoreEntry, ...]) -> tuple[LoreEntry, ...]:
	return tuple(
		entry
		for entry in entries
		if entry.entry_id is not None and entry.type_path is not None and entry.wiki is not None and entry.wiki.enabled is True
	)


def validate_registry_subtype_names(entries: tuple[LoreEntry, ...]) -> None:
	seen_subtype_names: dict[str, LoreEntry] = {}
	for entry in iter_registry_entries(entries):
		subtype_name = make_registry_subtype_name(entry.entry_id)
		existing_entry = seen_subtype_names.get(subtype_name)
		if existing_entry is None:
			seen_subtype_names[subtype_name] = entry
			continue
		raise ValueError(
			f"Generated registry subtype '/datum/lore_overhaul_entry/{subtype_name}' collides between "
			f"{format_entry_diagnostic(existing_entry)} and {format_entry_diagnostic(entry)}."
		)


def find_primary_icon(entry: LoreEntry) -> IconRecord | None:
	for icon_record in entry.icons:
		if icon_record.key == "icon":
			return icon_record
	return None


def render_override_block(entry: LoreEntry) -> str:
	assignments: list[str] = []
	if entry.name is not None:
		assignments.append(f"\tname = {format_dm_string(entry.name)}")
	if entry.description is not None:
		assignments.append(f"\tdesc = {format_dm_string(entry.description)}")
	if entry.special_desc_requirement is not None:
		requirement_constant = SPECIAL_DESC_REQUIREMENT_CONSTANTS[entry.special_desc_requirement]
		assignments.append(f"\tspecial_desc_requirement = {requirement_constant}")
	if entry.special_desc is not None:
		assignments.append(f"\tspecial_desc = {format_dm_string(entry.special_desc)}")
	for icon_record in entry.icons:
		if icon_record.key == "icon":
			assignments.append(f"\ticon = {format_dm_icon_path(icon_record.file)}")
			assignments.append(f"\ticon_state = {format_dm_string(icon_record.state)}")
		if icon_record.key == "worn_icon":
			assignments.append(f"\tworn_icon = {format_dm_icon_path(icon_record.file)}")
			assignments.append(f"\tworn_icon_state = {format_dm_string(icon_record.state)}")
		if icon_record.key == "inhand_icon":
			assignments.append(f"\tlefthand_file = {format_dm_icon_path(icon_record.file)}")
			assignments.append(f"\trighthand_file = {format_dm_icon_path(icon_record.file)}")
			assignments.append(f"\tinhand_icon_state = {format_dm_string(icon_record.state)}")
	if not assignments or entry.type_path is None:
		return ""
	return "\n".join([entry.type_path, *assignments])


def render_registry_block(entry: LoreEntry) -> str:
	return render_registry_block_with_label(entry, None)


def render_registry_block_with_label(
	entry: LoreEntry,
	target_label: str | None,
	target_base_name: str | None = None,
	target_base_description: str | None = None,
) -> str:
	if entry.entry_id is None or entry.type_path is None or entry.wiki is None or entry.wiki.enabled is not True:
		return ""

	assignments = [
		f"/datum/lore_overhaul_entry/{make_registry_subtype_name(entry.entry_id)}",
		f"\tentry_id = {format_dm_string(entry.entry_id)}",
		f"\ttarget_type = {entry.type_path}",
		"\twiki_enabled = TRUE",
	]
	if target_base_name is not None:
		assignments.append(f"\tbase_name = {format_dm_string(target_base_name)}")
	if target_base_description is not None:
		assignments.append(f"\tbase_description = {format_dm_string(target_base_description)}")

	if entry.wiki.slug is not None:
		assignments.append(f"\twiki_slug = {format_dm_string(entry.wiki.slug)}")
	if entry.wiki.summary is not None:
		assignments.append(f"\twiki_summary = {format_dm_string(entry.wiki.summary)}")
	if entry.wiki.export_icon is not None:
		assignments.append(f"\twiki_export_icon = {'TRUE' if entry.wiki.export_icon else 'FALSE'}")
	if entry.wiki.export_icon:
		primary_icon = find_primary_icon(entry)
		if primary_icon is not None:
			assignments.append(f"\twiki_icon_file = {format_dm_string(primary_icon.file)}")
			assignments.append(f"\twiki_icon_state = {format_dm_string(primary_icon.state)}")
	if entry.name is not None:
		assignments.append(f"\tdisplay_name = {format_dm_string(entry.name)}")
	if entry.description is not None:
		assignments.append(f"\tdisplay_description = {format_dm_string(entry.description)}")
	assignments.append(f"\ttype_label = {format_dm_string(target_label or entry.type_path)}")

	return "\n".join(assignments)


def render_autowiki_block(entry: LoreEntry) -> str:
	if entry.entry_id is None or entry.wiki is None or entry.wiki.enabled is not True:
		return ""
	if entry.wiki.slug is None:
		raise ValueError(f"Enabled lore entry {format_entry_diagnostic(entry)} has no AutoWiki slug.")
	subtype_name = autowiki_type_name(entry)
	return "\n".join([
		f"/datum/autowiki/lore_overhaul/{subtype_name}",
		f"\tpage = {format_dm_string(f'Template:Autowiki/AphelionLore/{entry.wiki.slug}')}",
		f"\tentry_type = /datum/lore_overhaul_entry/{subtype_name}",
	])


def _generated_header(
	*,
	tool_repo_revision: str | None = None,
	catalog_sha256: str | None = None,
) -> str:
	if tool_repo_revision is None and catalog_sha256 is None:
		return GENERATED_HEADER
	lines = [
		"/// THIS FILE IS GENERATED. DO NOT EDIT BY HAND.",
		"/// Source: tools/lore_editor/content",
	]
	if tool_repo_revision is not None:
		lines.append(f"/// Tool source revision: {tool_repo_revision}")
	if catalog_sha256 is not None:
		lines.append(f"/// Catalog snapshot SHA-256: {catalog_sha256}")
	return "\n".join(lines) + "\n"


def generate_dm(
	corpus: LoreCorpus,
	*,
	tool_repo_revision: str | None = None,
	catalog_sha256: str | None = None,
) -> str:
	"""Return the complete deterministic DM artifact."""
	sorted_entries = sort_entries(corpus.entries)
	validate_registry_subtype_names(sorted_entries)

	blocks: list[str] = []
	target_labels = {
		target.type_path: target.label
		for target in corpus.targets
		if target.type_path is not None
	}
	target_base_values = {
		target.type_path: (target.base_name, target.base_description)
		for target in corpus.targets
		if target.type_path is not None
	}
	for entry in sorted_entries:
		override_block = render_override_block(entry)
		if override_block:
			blocks.append(override_block)
		target_base_name, target_base_description = target_base_values.get(entry.type_path, (None, None))
		registry_block = render_registry_block_with_label(
			entry,
			target_labels.get(entry.type_path),
			target_base_name,
			target_base_description,
		)
		if registry_block:
			blocks.append(registry_block)
		autowiki_block = render_autowiki_block(entry)
		if autowiki_block:
			blocks.append(autowiki_block)

	header = _generated_header(
		tool_repo_revision=tool_repo_revision,
		catalog_sha256=catalog_sha256,
	)
	if not blocks:
		return f"{header}\n"
	return f"{header}\n" + "\n\n".join(blocks) + "\n"


def format_validation_error(repo_root: Path, corpus: LoreCorpus) -> str | None:
	issues = validate_corpus(repo_root, corpus)
	if not issues:
		return None
	formatted_issues = "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)
	return f"Lore corpus validation failed:\n{formatted_issues}"


def write_generated_dm(repo_root: Path, *, check_only: bool = False) -> None:
	"""Validate and write or compare the Aphelion DM artifact atomically."""
	resolved_root = repo_root.resolve()
	corpus = load_corpus(resolved_root)
	validation_error = format_validation_error(resolved_root, corpus)
	if validation_error is not None:
		raise ValueError(validation_error)

	rendered_dm = generate_dm(corpus)
	rendered_bytes = rendered_dm.encode("utf-8")
	layout = WorkspaceLayout.from_root(resolved_root)
	generated_path = resolved_root / layout.generated_dm_path

	if check_only:
		if not generated_path.exists():
			raise ValueError(f"Generated artifact is missing: {layout.generated_dm_path.as_posix()}")
		if generated_path.read_bytes() != rendered_bytes:
			raise ValueError(f"Generated artifact is stale: {layout.generated_dm_path.as_posix()}")
		return

	generated_path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=generated_path.parent,
		prefix=f"{generated_path.stem}.",
		suffix=".tmp",
	) as temp_file:
		temp_file.write(rendered_bytes)
		temp_file_path = Path(temp_file.name)

	try:
		os.replace(temp_file_path, generated_path)
	except Exception:
		if temp_file_path.exists():
			temp_file_path.unlink()
		raise
