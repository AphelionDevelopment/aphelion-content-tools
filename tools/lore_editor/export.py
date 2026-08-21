from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

from .app.manifest import ExportManifest, sha256_bytes
from .generate import generate_dm
from .source import load_corpus
from .validation import validate_corpus
from .workspace import WorkspaceLayout
from webapp.game_repository import validate_game_repository
from webapp.git_adapter import repository_revision, repository_status


ARTIFACT_RELATIVE_PATH = Path("modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm")
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class PreparedExport:
	directory: Path
	artifact_path: Path
	manifest: ExportManifest

	@property
	def manifest_path(self) -> Path:
		return self.directory / MANIFEST_FILENAME


def _resolve_child(root: Path, relative_path: Path) -> Path:
	if relative_path.is_absolute():
		raise ValueError(f"Export path must be repository-relative: {relative_path}")
	resolved_root = root.resolve()
	resolved_path = (resolved_root / relative_path).resolve()
	if not resolved_path.is_relative_to(resolved_root):
		raise ValueError(f"Export path escapes its root: {relative_path}")
	return resolved_path


def _atomic_write(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=path.parent,
		prefix=f".{path.name}.",
		suffix=".tmp",
	) as temporary_file:
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


def _validation_error(tool_root: Path, game_root: Path) -> str | None:
	corpus = load_corpus(tool_root)
	issues = validate_corpus(tool_root, corpus, asset_root=game_root)
	if not issues:
		return None
	formatted_issues = "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)
	return f"Lore export validation failed:\n{formatted_issues}"


def _catalog_snapshot(tool_root: Path) -> tuple[bytes, Path]:
	layout = WorkspaceLayout.from_root(tool_root)
	catalog_path = _resolve_child(tool_root, layout.targets_path)
	if not catalog_path.is_file():
		raise ValueError(f"Catalog snapshot is missing: {layout.targets_path.as_posix()}")
	return catalog_path.read_bytes(), catalog_path


def _new_stage_directory(stage_root: Path, generated_hash: str) -> Path:
	stage_root = stage_root.resolve()
	stage_root.mkdir(parents=True, exist_ok=True)
	stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	base_name = f"{stamp}-{generated_hash[:12]}"
	stage_directory = stage_root / base_name
	for suffix in range(100):
		candidate = stage_directory if suffix == 0 else stage_root / f"{base_name}-{suffix}"
		try:
			candidate.mkdir()
			return candidate
		except FileExistsError:
			continue
	raise ValueError("Could not allocate a unique export stage directory.")


def prepare_export(tool_root: Path, game_repo_root: Path, stage_root: Path) -> PreparedExport:
	"""Validate tool content and prepare a game-repository artifact without editing the game checkout."""
	resolved_tool_root = tool_root.resolve()
	resolved_game_root = game_repo_root.resolve()
	validate_game_repository(resolved_game_root)
	validation_error = _validation_error(resolved_tool_root, resolved_game_root)
	if validation_error is not None:
		raise ValueError(validation_error)

	corpus = load_corpus(resolved_tool_root)
	catalog_bytes, _ = _catalog_snapshot(resolved_tool_root)
	catalog_sha256 = sha256_bytes(catalog_bytes)
	tool_status = repository_status(resolved_tool_root)
	tool_revision = repository_revision(resolved_tool_root)
	game_revision = repository_revision(resolved_game_root)
	generated_bytes = generate_dm(
		corpus,
		tool_repo_revision=tool_revision,
		catalog_sha256=catalog_sha256,
	).encode("utf-8")
	generated_hash = sha256_bytes(generated_bytes)
	game_artifact_path = _resolve_child(resolved_game_root, ARTIFACT_RELATIVE_PATH)
	base_artifact_hash = sha256_bytes(game_artifact_path.read_bytes()) if game_artifact_path.is_file() else None
	manifest = ExportManifest(
		tool_repo_revision=tool_revision,
		tool_branch=tool_status.branch,
		catalog_sha256=catalog_sha256,
		game_repo_revision=game_revision,
		entry_ids=tuple(sorted(entry.entry_id for entry in corpus.entries if entry.entry_id is not None)),
		type_paths=tuple(sorted(entry.type_path for entry in corpus.entries if entry.type_path is not None)),
		generated_artifact_sha256=generated_hash,
		base_artifact_sha256=base_artifact_hash,
	)

	stage_directory = _new_stage_directory(stage_root, generated_hash)
	try:
		stage_artifact_path = stage_directory / ARTIFACT_RELATIVE_PATH
		_atomic_write(stage_artifact_path, generated_bytes)
		_atomic_write(
			stage_directory / MANIFEST_FILENAME,
			(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
		)
	except Exception:
		shutil.rmtree(stage_directory, ignore_errors=True)
		raise
	return PreparedExport(directory=stage_directory, artifact_path=stage_artifact_path, manifest=manifest)


def _load_prepared_manifest(stage_directory: Path) -> ExportManifest:
	manifest_path = _resolve_child(stage_directory, Path(MANIFEST_FILENAME))
	if not manifest_path.is_file():
		raise ValueError(f"Export manifest is missing: {manifest_path}")
	try:
		payload = json.loads(manifest_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise ValueError(f"Export manifest could not be read: {exc}") from exc
	return ExportManifest.from_dict(payload)


def apply_export(stage_directory: Path, game_repo_root: Path, *, allow_dirty: bool = False) -> Path:
	"""Apply a prepared artifact only when the recorded clean-game checks still hold.

	`allow_dirty` lets a caller override the uncommitted-changes block after the user has explicitly
	confirmed it (the export only ever touches the one generated artifact file, so overwriting it
	alongside other uncommitted game-repo changes is a deliberate, reviewable choice) -- unresolved Git
	conflicts remain a hard block regardless, since applying on top of those is never safe.
	"""
	resolved_stage_directory = stage_directory.resolve()
	resolved_game_root = game_repo_root.resolve()
	validate_game_repository(resolved_game_root)
	manifest = _load_prepared_manifest(resolved_stage_directory)
	stage_artifact_path = _resolve_child(resolved_stage_directory, ARTIFACT_RELATIVE_PATH)
	if not stage_artifact_path.is_file():
		raise ValueError(f"Prepared export artifact is missing: {ARTIFACT_RELATIVE_PATH.as_posix()}")
	stage_bytes = stage_artifact_path.read_bytes()
	if sha256_bytes(stage_bytes) != manifest.generated_artifact_sha256:
		raise ValueError("Prepared export artifact hash does not match its manifest.")

	status = repository_status(resolved_game_root)
	if status.conflicted:
		raise ValueError("The game checkout has unresolved Git conflicts; resolve them in GitHub Desktop first.")
	if status.dirty and not allow_dirty:
		raise ValueError("The game checkout has uncommitted changes; review or commit them in GitHub Desktop before applying an export.")
	if repository_revision(resolved_game_root) != manifest.game_repo_revision:
		raise ValueError("The game checkout revision changed after this export was prepared; prepare a new export.")

	game_artifact_path = _resolve_child(resolved_game_root, ARTIFACT_RELATIVE_PATH)
	current_bytes = game_artifact_path.read_bytes() if game_artifact_path.is_file() else None
	current_hash = sha256_bytes(current_bytes) if current_bytes is not None else None
	if current_hash != manifest.base_artifact_sha256:
		raise ValueError("The generated game artifact changed after this export was prepared; prepare a new export.")
	if not game_artifact_path.parent.is_dir():
		raise ValueError(f"The game lore-overhaul module is missing: {game_artifact_path.parent}")

	_atomic_write(game_artifact_path, stage_bytes)
	return game_artifact_path
