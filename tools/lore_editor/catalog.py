from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .model import SUPPORTED_ICON_KEYS
from .app.manifest import CatalogManifest, sha256_bytes
from .app.storage import canonical_json_bytes
from .git_adapter import repository_remote_url, repository_revision
from .source import TARGETS_PATH, read_json_file, resolve_repo_path
from .validation import TYPE_PATH_PATTERN
from .workspace import WorkspaceLayout

PROBE_OUTPUT_PATH = Path("data/lore_overhaul_targets.json")
BUILD_ENTRYPOINT = Path("tools/build/build.bat")
COMPILED_DMB_PATH = Path("tgstation.dmb")
GAME_REPOSITORY_MARKER_PATH = Path("tgstation.dme")
EXPECTED_GAME_REPOSITORY_REMOTE_HINT = "meridian-rift"
FIELD_PROFILE_ATOM_LIKE = "atom_like"
FIELD_PROFILE_NAMED_DATUM = "named_datum"
SUPPORTED_FIELD_PROFILES = frozenset((FIELD_PROFILE_ATOM_LIKE, FIELD_PROFILE_NAMED_DATUM))
EDITABLE_ROOTS = (
	{"type_path": "/datum/language", "field_profile": FIELD_PROFILE_NAMED_DATUM},
	{"type_path": "/datum/species", "field_profile": FIELD_PROFILE_NAMED_DATUM},
	{"type_path": "/obj/item", "field_profile": FIELD_PROFILE_ATOM_LIKE},
	{"type_path": "/obj/machinery", "field_profile": FIELD_PROFILE_ATOM_LIKE},
)


def _read_probe_json(repo_root: Path, probe_output_path: Path) -> object:
    if probe_output_path.is_absolute():
        try:
            relative_path = probe_output_path.resolve().relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Repository path escapes root: {probe_output_path}") from exc
    else:
        relative_path = probe_output_path
    return read_json_file(repo_root, relative_path)


def _is_type_path_within_root(type_path: str, editable_root: str) -> bool:
    return type_path == editable_root or type_path.startswith(f"{editable_root}/")


def _validate_string_field(target: dict[str, object], field_name: str) -> str:
    value = target.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Catalog target field '{field_name}' must be a non-empty string.")
    return value


def _validate_type_path_field(target: dict[str, object], field_name: str) -> str:
    value = _validate_string_field(target, field_name)
    if not TYPE_PATH_PATTERN.fullmatch(value):
        raise ValueError(f"Catalog target field '{field_name}' must be an absolute BYOND path in snake_case segments.")
    return value


def _normalize_base_values(raw_base_values: object) -> dict[str, object]:
    if not isinstance(raw_base_values, dict):
        raise ValueError("Catalog target field 'base_values' must be an object.")

    if set(raw_base_values) != {"name", "description"}:
        raise ValueError("Catalog target field 'base_values' must contain exactly 'name' and 'description'.")

    normalized_base_values: dict[str, object] = {}
    for field_name in ("name", "description"):
        value = raw_base_values[field_name]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"Catalog base value '{field_name}' must be a string or null.")
        normalized_base_values[field_name] = value
    return normalized_base_values


def _normalize_icon_metadata(raw_icon_metadata: object) -> dict[str, object]:
    if raw_icon_metadata == []:
        raw_icon_metadata = {}
    if not isinstance(raw_icon_metadata, dict):
        raise ValueError("Catalog target field 'icon_metadata' must be an object.")

    normalized_icon_metadata: dict[str, object] = {}
    for key in sorted(raw_icon_metadata):
        if key not in SUPPORTED_ICON_KEYS:
            raise ValueError(f"Catalog target field 'icon_metadata.{key}' is not supported.")
        raw_icon_record = raw_icon_metadata[key]
        if not isinstance(raw_icon_record, dict):
            raise ValueError(f"Catalog icon metadata '{key}' must be an object.")

        if not {"file", "state"}.issubset(raw_icon_record) or set(raw_icon_record) - {"file", "state", "available_states"}:
            raise ValueError(
                f"Catalog icon metadata '{key}' must contain 'file' and 'state', with no unsupported fields."
            )

        icon_file = raw_icon_record.get("file")
        icon_state = raw_icon_record.get("state")
        available_states = raw_icon_record.get("available_states")
        if not isinstance(icon_file, str) or not icon_file:
            raise ValueError(f"Catalog icon metadata '{key}.file' must be a non-empty string.")
        if not isinstance(icon_state, str) or not icon_state:
            raise ValueError(f"Catalog icon metadata '{key}.state' must be a non-empty string.")
        if available_states is not None and (not isinstance(available_states, list) or any(not isinstance(state, str) or not state for state in available_states)):
            raise ValueError(f"Catalog icon metadata '{key}.available_states' must be an array of non-empty strings.")

        normalized_icon_metadata[key] = {
            "file": icon_file.replace("\\", "/"),
            "state": icon_state,
        }
    return normalized_icon_metadata


def _expected_profile_by_root(editable_root: str) -> str | None:
    for configured_root in EDITABLE_ROOTS:
        if configured_root["type_path"] == editable_root:
            return str(configured_root["field_profile"])
    return None


def _normalize_target(raw_target: object) -> dict[str, object]:
    if not isinstance(raw_target, dict):
        raise ValueError("Each catalog target must be a JSON object.")

    type_path = _validate_type_path_field(raw_target, "type_path")
    label = _validate_string_field(raw_target, "label")
    editable_root = _validate_type_path_field(raw_target, "editable_root")
    parent_type = _validate_type_path_field(raw_target, "parent_type")
    field_profile = _validate_string_field(raw_target, "field_profile")
    if field_profile not in SUPPORTED_FIELD_PROFILES:
        raise ValueError(f"Catalog target field 'field_profile' must be one of {sorted(SUPPORTED_FIELD_PROFILES)!r}.")

    expected_profile = _expected_profile_by_root(editable_root)
    if expected_profile is None:
        raise ValueError(f"Catalog target '{type_path}' uses unconfigured editable root '{editable_root}'.")
    if field_profile != expected_profile:
        raise ValueError(
            f"Catalog target '{type_path}' reports field profile '{field_profile}' but root '{editable_root}' requires '{expected_profile}'."
        )
    if not _is_type_path_within_root(type_path, editable_root):
        raise ValueError(f"Catalog target '{type_path}' is outside configured editable root '{editable_root}'.")

    base_values = _normalize_base_values(raw_target.get("base_values"))
    icon_metadata = _normalize_icon_metadata(raw_target.get("icon_metadata", {}))

    return {
        "type_path": type_path,
        "label": label,
        "editable_root": editable_root,
        "parent_type": parent_type,
        "field_profile": field_profile,
        "base_values": base_values,
        "icon_metadata": icon_metadata,
    }


def normalize_targets(raw_targets: object) -> list[dict[str, object]]:
    if not isinstance(raw_targets, list):
        raise ValueError(f"{TARGETS_PATH.as_posix()}: expected a JSON array")

    normalized_targets = [_normalize_target(raw_target) for raw_target in raw_targets]
    normalized_targets.sort(key=lambda target: str(target["type_path"]))

    seen_type_paths: set[str] = set()
    for target in normalized_targets:
        type_path = str(target["type_path"])
        if type_path in seen_type_paths:
            raise ValueError(f"Catalog target '{type_path}' appears more than once.")
        seen_type_paths.add(type_path)
    return normalized_targets


def _write_targets(repo_root: Path, targets: list[dict[str, object]]) -> bytes:
	targets_path = resolve_repo_path(repo_root, WorkspaceLayout.from_root(repo_root).targets_path)
	rendered_bytes = canonical_json_bytes(targets)
	targets_path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=targets_path.parent,
		prefix=f"{targets_path.stem}.",
		suffix=".tmp",
	) as temp_file:
		temp_file.write(rendered_bytes)
		temp_file_path = Path(temp_file.name)

	try:
		os.replace(temp_file_path, targets_path)
	except Exception:
		if temp_file_path.exists():
			temp_file_path.unlink()
		raise
	return rendered_bytes


def _write_catalog_manifest(repo_root: Path, game_repo_root: Path, targets_bytes: bytes, target_count: int) -> None:
	resolved_root = repo_root.resolve()
	try:
		game_revision = repository_revision(game_repo_root)
	except (OSError, ValueError):
		game_revision = "unknown"
	manifest = CatalogManifest(
		snapshot_sha256=sha256_bytes(targets_bytes),
		game_repo_revision=game_revision,
		generated_at=datetime.now(timezone.utc).isoformat(),
		target_count=target_count,
	)
	manifest_path = resolve_repo_path(resolved_root, WorkspaceLayout.from_root(resolved_root).targets_path).with_name("manifest.json")
	manifest_bytes = canonical_json_bytes(manifest.to_dict())
	manifest_path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=manifest_path.parent,
		prefix=f"{manifest_path.stem}.",
		suffix=".tmp",
	) as temp_file:
		temp_file.write(manifest_bytes)
		temp_file_path = Path(temp_file.name)
	try:
		os.replace(temp_file_path, manifest_path)
	except Exception:
		if temp_file_path.exists():
			temp_file_path.unlink()
		raise


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_dreamdaemon_path() -> str:
    candidate_paths: list[Path] = []
    dm_env = os.environ.get("DM_EXE")
    if dm_env:
        for configured_path in dm_env.split(","):
            dm_path = Path(configured_path.strip())
            if dm_path.name.lower() == "dm.exe":
                candidate_paths.append(dm_path.with_name("DreamDaemon.exe"))
    candidate_paths.extend(
        (
            Path(r"C:\Program Files\BYOND\bin\DreamDaemon.exe"),
            Path(r"C:\Program Files (x86)\BYOND\bin\DreamDaemon.exe"),
        )
    )

    for candidate_path in candidate_paths:
        if candidate_path.is_file():
            return str(candidate_path)

    discovered_path = shutil.which("DreamDaemon.exe")
    if discovered_path is not None:
        return discovered_path
    raise ValueError("DreamDaemon.exe was not found in the standard BYOND install locations.")


def _run_external_command(
    repo_root: Path,
    command: list[str],
    failure_prefix: str,
    *,
    allow_nonzero_exit: bool = False,
) -> int:
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line.rstrip("\r\n"))
        sys.stdout.write(line)
    return_code = process.wait()
    if return_code != 0 and not allow_nonzero_exit:
        joined_output = "\n".join(output_lines[-40:])
        raise ValueError(f"{failure_prefix} failed with exit code {return_code}.\n{joined_output}")
    return return_code


def _run_catalog_probe(repo_root: Path) -> Path:
	build_entrypoint = resolve_repo_path(repo_root, BUILD_ENTRYPOINT)
	probe_output_path = resolve_repo_path(repo_root, PROBE_OUTPUT_PATH)
	compiled_dmb_path = resolve_repo_path(repo_root, COMPILED_DMB_PATH)
	probe_started_at_ns = time.time_ns()
	if probe_output_path.exists():
		probe_output_path.unlink()

	_run_external_command(
		repo_root,
		[
			"cmd.exe",
			"/c",
			str(build_entrypoint),
			"dm",
			"--define=LORE_CATALOG",
		],
		"Lore catalog probe compile",
	)

	if not compiled_dmb_path.exists():
		raise ValueError(f"Lore catalog probe compile did not produce {COMPILED_DMB_PATH.as_posix()}.")
	if compiled_dmb_path.stat().st_mtime_ns <= probe_started_at_ns:
		raise ValueError(f"Lore catalog probe compile did not produce a fresh {COMPILED_DMB_PATH.as_posix()}.")

	dreamdaemon_path = _find_dreamdaemon_path()
	port = _find_free_port()
	_run_external_command(
		repo_root,
		[
			dreamdaemon_path,
			str(compiled_dmb_path),
			str(port),
			"-close",
			"-trusted",
			"-verbose",
			"-params",
			"log-directory=ci",
		],
		"Lore catalog probe runtime",
		allow_nonzero_exit=True,
	)

	if not probe_output_path.exists():
		raise ValueError(f"Lore catalog probe did not produce {PROBE_OUTPUT_PATH.as_posix()}.")
	return probe_output_path


def validate_game_repository(game_repo_root: Path) -> None:
	"""Raise if the given path does not look like a Meridian-Rift checkout.

	Checks a content marker (tgstation.dme) that any BYOND/tgstation-family checkout must have, and,
	when the path is a Git repository with an 'origin' remote configured, that the remote URL looks
	like Meridian-Rift. A path with no Git remote configured is accepted based on the content marker
	alone, since there is nothing further to check.
	"""
	resolved_root = game_repo_root.resolve()
	if not resolved_root.is_dir():
		raise ValueError(f"Game repository does not exist: {game_repo_root}")
	if not (resolved_root / GAME_REPOSITORY_MARKER_PATH).is_file():
		raise ValueError(
			f"'{resolved_root}' does not look like a Meridian-Rift checkout "
			f"({GAME_REPOSITORY_MARKER_PATH.as_posix()} is missing)."
		)
	remote_url = repository_remote_url(resolved_root)
	if remote_url is not None and EXPECTED_GAME_REPOSITORY_REMOTE_HINT not in remote_url.casefold():
		raise ValueError(
			f"'{resolved_root}' has a Git remote that does not look like Meridian-Rift: {remote_url}"
		)


def read_current_targets(repo_root: Path) -> list[dict[str, object]]:
	"""Best-effort read of the currently committed targets.json, for before/after drift comparison."""
	resolved_root = repo_root.resolve()
	try:
		raw = read_json_file(resolved_root, WorkspaceLayout.from_root(resolved_root).targets_path)
	except (OSError, ValueError):
		return []
	return raw if isinstance(raw, list) and all(isinstance(item, dict) for item in raw) else []


@dataclass(frozen=True)
class CatalogDriftReport:
	removed_type_paths: tuple[str, ...]
	changed_type_paths: tuple[str, ...]
	stale_entry_type_paths: tuple[str, ...]

	@property
	def has_drift(self) -> bool:
		return bool(self.removed_type_paths or self.changed_type_paths)


_DRIFT_COMPARISON_FIELDS = ("label", "field_profile", "editable_root", "parent_type")


def _target_drift_signature(target: dict[str, object]) -> tuple[object, ...]:
	base_values = target.get("base_values")
	name = base_values.get("name") if isinstance(base_values, dict) else None
	description = base_values.get("description") if isinstance(base_values, dict) else None
	return (*(target.get(field) for field in _DRIFT_COMPARISON_FIELDS), name, description)


def compute_catalog_drift(
	old_targets: list[dict[str, object]],
	new_targets: list[dict[str, object]],
	entry_type_paths: frozenset[str],
) -> CatalogDriftReport:
	"""Compare a catalog snapshot before and after a refresh to report what changed."""
	old_by_type = {
		str(target["type_path"]): target
		for target in old_targets
		if isinstance(target.get("type_path"), str)
	}
	new_by_type = {
		str(target["type_path"]): target
		for target in new_targets
		if isinstance(target.get("type_path"), str)
	}
	removed = tuple(sorted(set(old_by_type) - set(new_by_type)))
	changed = tuple(sorted(
		type_path
		for type_path in set(old_by_type) & set(new_by_type)
		if _target_drift_signature(old_by_type[type_path]) != _target_drift_signature(new_by_type[type_path])
	))
	drifted = frozenset(removed) | frozenset(changed)
	stale_entries = tuple(sorted(entry_type_paths & drifted))
	return CatalogDriftReport(removed_type_paths=removed, changed_type_paths=changed, stale_entry_type_paths=stale_entries)


def refresh_catalog(repo_root: Path, *, game_repo_root: Path | None = None) -> list[dict[str, object]]:
	"""Run the conditional BYOND probe and atomically update targets.json."""
	resolved_root = repo_root.resolve()
	resolved_game_root = (game_repo_root or repo_root).resolve()
	if game_repo_root is not None:
		validate_game_repository(resolved_game_root)
	probe_output_path = _run_catalog_probe(resolved_game_root)
	raw_targets = _read_probe_json(resolved_game_root, probe_output_path)
	targets = normalize_targets(raw_targets)
	targets_bytes = _write_targets(resolved_root, targets)
	_write_catalog_manifest(resolved_root, resolved_game_root, targets_bytes, len(targets))
	return targets
