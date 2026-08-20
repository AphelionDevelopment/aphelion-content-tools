from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from webapp.git_adapter import GitAdapterError, list_tracked_files
from .markers import MarkerEdge, parse_markers


MODULE_ROOTS = (
	("nova", Path("modular_nova/modules")),
	("aphelion", Path("modular_aphelion/modules")),
)
MASTER_FILES_ROOTS = (
	("nova", Path("modular_nova/master_files")),
	("aphelion", Path("modular_aphelion/master_files")),
)
CORE_SCAN_ROOT = Path("code")
MARKER_FILE_SUFFIXES = frozenset((".dm", ".dmm", ".dmf"))
FULL_TREE_WALK_EXCLUDED_DIR_NAMES = frozenset((".git", "__pycache__", "node_modules", ".venv"))


@dataclass(frozen=True)
class ModuleNode:
	id: str
	owner: str
	path: str
	has_readme: bool


@dataclass(frozen=True)
class MasterFileNode:
	owner: str
	path: str
	core_path: str


def scan_modules(game_repo_root: Path) -> tuple[ModuleNode, ...]:
	modules: list[ModuleNode] = []
	for owner, relative_root in MODULE_ROOTS:
		root = game_repo_root / relative_root
		if not root.is_dir():
			continue
		for entry in sorted(root.iterdir(), key=lambda item: item.name):
			if not entry.is_dir():
				continue
			modules.append(ModuleNode(
				id=entry.name,
				owner=owner,
				path=entry.relative_to(game_repo_root).as_posix(),
				has_readme=(entry / "readme.md").is_file(),
			))
	return tuple(modules)


def scan_master_files(game_repo_root: Path) -> tuple[MasterFileNode, ...]:
	overrides: list[MasterFileNode] = []
	for owner, relative_root in MASTER_FILES_ROOTS:
		root = game_repo_root / relative_root
		if not root.is_dir():
			continue
		for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
			if not path.is_file():
				continue
			overrides.append(MasterFileNode(
				owner=owner,
				path=path.relative_to(game_repo_root).as_posix(),
				core_path=path.relative_to(root).as_posix(),
			))
	return tuple(overrides)


def _walk_full_tree_without_git(game_repo_root: Path) -> tuple[str, ...]:
	paths: list[str] = []
	for path in game_repo_root.rglob("*"):
		if not path.is_file():
			continue
		if FULL_TREE_WALK_EXCLUDED_DIR_NAMES.intersection(path.relative_to(game_repo_root).parts[:-1]):
			continue
		paths.append(path.relative_to(game_repo_root).as_posix())
	return tuple(sorted(paths))


def scan_full_tree(game_repo_root: Path) -> tuple[str, ...]:
	"""Return every file path in the checkout, repo-relative and posix-styled, sorted.

	Prefers Git-tracked files (`git ls-files`) so generated/build output and scratch files stay out of
	the graph. Falls back to a filesystem walk -- excluding common non-content directories -- for a
	checkout with no `.git` directory, which `validate_game_repository` otherwise permits.
	"""
	try:
		return list_tracked_files(game_repo_root)
	except GitAdapterError:
		return _walk_full_tree_without_git(game_repo_root)


def scan_core_markers(game_repo_root: Path, known_module_ids: frozenset[str]) -> dict[str, tuple[MarkerEdge, ...]]:
	"""Walk the core code tree and return {repo-relative path: markers} for files with at least one marker."""
	core_root = game_repo_root / CORE_SCAN_ROOT
	if not core_root.is_dir():
		return {}
	markers_by_path: dict[str, tuple[MarkerEdge, ...]] = {}
	for path in sorted(core_root.rglob("*"), key=lambda item: item.as_posix()):
		if not path.is_file() or path.suffix.casefold() not in MARKER_FILE_SUFFIXES:
			continue
		try:
			text = path.read_text(encoding="utf-8", errors="replace")
		except OSError:
			continue
		markers = parse_markers(text, known_module_ids)
		if markers:
			markers_by_path[path.relative_to(game_repo_root).as_posix()] = tuple(markers)
	return markers_by_path
