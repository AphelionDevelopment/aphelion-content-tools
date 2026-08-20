from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .model import (
    CatalogTarget,
    IconRecord,
    LoreCorpus,
    LoreEntry,
    SUPPORTED_ICON_KEYS,
    WikiRecord,
    as_bool,
    as_object,
    as_string,
    freeze_json,
)
from .workspace import WorkspaceLayout

CONFIG_ROOT = Path("config/aphelion/lore_overhaul")
TARGETS_PATH = CONFIG_ROOT / "targets.json"
ENTITIES_ROOT = CONFIG_ROOT / "entities"


_CATALOG_TARGET_CACHE: dict[tuple[Path, int, int], tuple[CatalogTarget, ...]] = {}
_CATALOG_TARGET_CACHE_LOCK = Lock()


def resolve_repo_path(repo_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise ValueError(f"Absolute repository path is not allowed: {relative_path}")
    resolved_root = repo_root.resolve()
    resolved_path = (resolved_root / relative_path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"Repository path escapes root: {relative_path}")
    return resolved_path


def read_json_file(repo_root: Path, relative_path: Path) -> object:
    source_path = resolve_repo_path(repo_root, relative_path)
    try:
        return json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{relative_path.as_posix()}: malformed JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc


def make_catalog_target(raw_target: object) -> CatalogTarget:
    frozen_target = freeze_json(raw_target)
    target_object = as_object(frozen_target)
    type_path = None
    label = None
    editable_root = None
    parent_type = None
    base_name = None
    base_description = None
    field_profile = None
    if target_object is not None:
        type_path = as_string(target_object.get("type_path"))
        label = as_string(target_object.get("label"))
        editable_root = as_string(target_object.get("editable_root"))
        parent_type = as_string(target_object.get("parent_type"))
        base_values = as_object(target_object.get("base_values"))
        if base_values is not None:
            base_name = as_string(base_values.get("name"))
            base_description = as_string(base_values.get("description"))
        field_profile = as_string(target_object.get("field_profile"))
    return CatalogTarget(
        raw_data=frozen_target,
        type_path=type_path,
        label=label,
        editable_root=editable_root,
        parent_type=parent_type,
        base_name=base_name,
        base_description=base_description,
        field_profile=field_profile,
    )


def make_lore_entry(source_path: Path, raw_entry: object) -> LoreEntry:
    frozen_entry = freeze_json(raw_entry)
    entry_object = as_object(frozen_entry)
    entry_id = None
    type_path = None
    name = None
    description = None
    special_desc_requirement = None
    special_desc = None
    icons: list[IconRecord] = []
    wiki = None

    if entry_object is not None:
        entry_id = as_string(entry_object.get("id"))
        type_path = as_string(entry_object.get("type_path"))
        name = as_string(entry_object.get("name"))
        description = as_string(entry_object.get("description"))
        special_desc_requirement = as_string(entry_object.get("special_desc_requirement"))
        special_desc = as_string(entry_object.get("special_desc"))

        icon_object = as_object(entry_object.get("icons"))
        if icon_object is not None:
            for key in SUPPORTED_ICON_KEYS:
                icon_value = as_object(icon_object.get(key))
                if icon_value is None:
                    continue
                icon_file = as_string(icon_value.get("file"))
                icon_state = as_string(icon_value.get("state"))
                if icon_file is None or icon_state is None:
                    continue
                icons.append(IconRecord(key=key, file=icon_file, state=icon_state))

        wiki_object = as_object(entry_object.get("wiki"))
        if wiki_object is not None:
            wiki = WikiRecord(
                enabled=as_bool(wiki_object.get("enabled")),
                slug=as_string(wiki_object.get("slug")),
                summary=as_string(wiki_object.get("summary")),
                export_icon=as_bool(wiki_object.get("export_icon")),
            )

    return LoreEntry(
        source_path=source_path,
        entry_id=entry_id,
        type_path=type_path,
        name=name,
        description=description,
        special_desc_requirement=special_desc_requirement,
        special_desc=special_desc,
        icons=tuple(icons),
        wiki=wiki,
        raw_data=frozen_entry,
    )


def iter_raw_entries(raw_document: object) -> tuple[object, ...]:
    if isinstance(raw_document, list):
        return tuple(raw_document)
    return (raw_document,)


def iter_entity_paths(repo_root: Path) -> list[Path]:
    layout = WorkspaceLayout.from_root(repo_root)
    entities_root = resolve_repo_path(repo_root, layout.entities_root)
    if not entities_root.exists():
        return []
    entity_paths = []
    for entity_path in entities_root.rglob("*.json"):
        resolved_path = entity_path.resolve()
        if not resolved_path.is_relative_to(repo_root.resolve()):
            raise ValueError(f"Repository path escapes root: {entity_path}")
        entity_paths.append(resolved_path.relative_to(repo_root.resolve()))
    entity_paths.sort(key=lambda path: path.as_posix())
    return entity_paths


def load_catalog_targets(repo_root: Path) -> tuple[CatalogTarget, ...]:
    resolved_root = repo_root.resolve()
    layout = WorkspaceLayout.from_root(resolved_root)
    targets_path = resolve_repo_path(resolved_root, layout.targets_path)
    try:
        targets_stat = targets_path.stat()
    except FileNotFoundError:
        targets_stat = None
    cache_key = (
        resolved_root,
        targets_stat.st_mtime_ns if targets_stat is not None else 0,
        targets_stat.st_size if targets_stat is not None else 0,
    )
    with _CATALOG_TARGET_CACHE_LOCK:
        cached_targets = _CATALOG_TARGET_CACHE.get(cache_key)
        if cached_targets is not None:
            return cached_targets

    raw_targets = read_json_file(resolved_root, layout.targets_path)
    if not isinstance(raw_targets, list):
        raise ValueError(f"{layout.targets_path.as_posix()}: expected a JSON array")
    targets = tuple(make_catalog_target(target) for target in raw_targets)
    with _CATALOG_TARGET_CACHE_LOCK:
        for cached_key in tuple(_CATALOG_TARGET_CACHE):
            if cached_key[0] == resolved_root:
                del _CATALOG_TARGET_CACHE[cached_key]
        _CATALOG_TARGET_CACHE[cache_key] = targets
    return targets


def load_corpus(repo_root: Path) -> LoreCorpus:
    resolved_root = repo_root.resolve()
    targets = load_catalog_targets(resolved_root)
    entries_list: list[LoreEntry] = []
    for source_path in iter_entity_paths(resolved_root):
        raw_document = read_json_file(resolved_root, source_path)
        for raw_entry in iter_raw_entries(raw_document):
            entries_list.append(make_lore_entry(source_path, raw_entry))
    entries = tuple(entries_list)
    return LoreCorpus(targets=targets, entries=entries)
