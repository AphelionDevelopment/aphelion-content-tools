from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
FrozenJson: TypeAlias = JsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]

SUPPORTED_ICON_KEYS = ("icon", "worn_icon", "inhand_icon")
SUPPORTED_SPECIAL_DESC_REQUIREMENTS = (
	"contractor",
	"faction",
	"job",
	"mindshield",
	"none",
	"role",
	"syndicate",
	"syndicate_toy",
)


def freeze_json(value: object) -> FrozenJson:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, dict):
        return MappingProxyType({str(key): freeze_json(item) for key, item in value.items()})
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def thaw_json(value: FrozenJson) -> object:
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    return value


def as_object(value: FrozenJson | None) -> Mapping[str, FrozenJson] | None:
    if isinstance(value, Mapping):
        return value
    return None


def as_string(value: FrozenJson | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def as_bool(value: FrozenJson | None) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str
    severity: str


@dataclass(frozen=True)
class IconRecord:
    key: str
    file: str
    state: str


@dataclass(frozen=True)
class WikiRecord:
    enabled: bool | None
    slug: str | None
    summary: str | None
    export_icon: bool | None


@dataclass(frozen=True)
class CatalogTarget:
	raw_data: FrozenJson
	type_path: str | None
	label: str | None
	editable_root: str | None
	parent_type: str | None
	base_name: str | None
	base_description: str | None
	field_profile: str | None


@dataclass(frozen=True)
class LoreEntry:
    source_path: Path
    entry_id: str | None
    type_path: str | None
    name: str | None
    description: str | None
    special_desc_requirement: str | None
    special_desc: str | None
    icons: tuple[IconRecord, ...]
    wiki: WikiRecord | None
    raw_data: FrozenJson


@dataclass(frozen=True)
class LoreCorpus:
    targets: tuple[CatalogTarget, ...]
    entries: tuple[LoreEntry, ...]


@dataclass(frozen=True)
class GroupRecord:
	id: str
	label: str
	color: str
	keywords: tuple[str, ...]
	type_path_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class GroupConfig:
	groups: tuple[GroupRecord, ...]
	assignments: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ReviewRecord:
	status: str
	reviewed_by: str
	reviewed_at: str
	notes: str
