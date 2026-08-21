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


@dataclass(frozen=True)
class ModuleContent:
	text: str
	file_count: int
	total_bytes: int


@dataclass(frozen=True)
class CoreFileContent:
	text: str
	size_bytes: int
	line_count: int


def scan_module_file_texts(game_repo_root: Path, modules: tuple[ModuleNode, ...]) -> dict[str, ModuleContent]:
	"""Read every .dm/.dmm/.dmf file in each module, keyed by the module's own repo-relative path.

	Used both for cross-module reference detection and for the module node's size/file-count metadata --
	one read pass over each module's files serves both, rather than re-walking the tree twice.
	"""
	contents: dict[str, ModuleContent] = {}
	for module in modules:
		module_root = game_repo_root / module.path
		chunks: list[str] = []
		file_count = 0
		total_bytes = 0
		for path in sorted(module_root.rglob("*"), key=lambda item: item.as_posix()):
			if not path.is_file() or path.suffix.casefold() not in MARKER_FILE_SUFFIXES:
				continue
			try:
				data = path.read_bytes()
			except OSError:
				continue
			file_count += 1
			total_bytes += len(data)
			chunks.append(data.decode("utf-8", errors="replace"))
		contents[module.path] = ModuleContent(text="\n".join(chunks), file_count=file_count, total_bytes=total_bytes)
	return contents


def scan_core_file_texts(game_repo_root: Path, core_paths: frozenset[str]) -> dict[str, CoreFileContent]:
	"""Read every given core-file path directly (no tree walk -- the caller already knows exactly which
	paths are core files), keyed by that same repo-relative path."""
	contents: dict[str, CoreFileContent] = {}
	for core_path in core_paths:
		path = game_repo_root / core_path
		if not path.is_file():
			continue
		try:
			data = path.read_bytes()
		except OSError:
			continue
		text = data.decode("utf-8", errors="replace")
		if not text:
			line_count = 0
		else:
			line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
		contents[core_path] = CoreFileContent(text=text, size_bytes=len(data), line_count=line_count)
	return contents


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
