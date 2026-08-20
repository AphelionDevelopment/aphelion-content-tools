from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from webapp.game_repository import validate_game_repository
from webapp.git_adapter import repository_revision
from webapp.json_storage import canonical_json_bytes
from webapp.path_safety import resolve_repo_path
from .manifest import GraphManifest, sha256_bytes
from .markers import MarkerEdge
from .scanner import scan_core_markers, scan_full_tree, scan_master_files, scan_modules


GRAPH_INDEX_PATH = Path("tools/content_graph/cache/index.json")
GRAPH_MANIFEST_PATH = Path("tools/content_graph/cache/manifest.json")


def _module_node_id(owner: str, module_id: str) -> str:
	return f"module:{owner}:{module_id}"


def _master_file_node_id(owner: str, path: str) -> str:
	return f"master_file:{owner}:{path}"


def _core_file_node_id(path: str) -> str:
	return f"core_file:{path}"


ROOT_DIR_ID = "dir:."


def _basename(posix_path: str) -> str:
	return posix_path.rsplit("/", 1)[-1]


def _parent_posix(posix_path: str) -> str:
	return posix_path.rsplit("/", 1)[0] if "/" in posix_path else ""


def _add_full_tree(
	nodes: list[dict[str, object]],
	edges: list[dict[str, object]],
	path_to_id: dict[str, str],
	tracked_paths: tuple[str, ...],
) -> int:
	"""Add directory/file nodes and `contains` edges for every tracked path not already represented.

	`path_to_id` is pre-seeded with the paths already covered by module/master_file/core_file nodes, so
	this only mints generic `dir:`/`file:` nodes for the rest of the checkout -- while still wiring the
	existing specialized nodes into the same containment tree, rooted at `ROOT_DIR_ID`. Returns the
	total number of unique directories in the tree (including module directories and the root).
	"""
	dir_created: set[str] = set()

	def ensure_dir(dir_posix: str) -> str:
		if dir_posix == "":
			node_id = ROOT_DIR_ID
		else:
			node_id = path_to_id.get(dir_posix, f"dir:{dir_posix}")
		if node_id in dir_created:
			return node_id
		dir_created.add(node_id)
		parent_id = ensure_dir(_parent_posix(dir_posix)) if dir_posix != "" else None
		if dir_posix not in path_to_id:
			nodes.append({
				"id": node_id,
				"kind": "directory",
				"path": dir_posix or ".",
				"name": _basename(dir_posix) if dir_posix else "(repository root)",
			})
		if parent_id is not None:
			edges.append({"source": parent_id, "target": node_id, "relation": "contains"})
		return node_id

	for file_path in tracked_paths:
		parent_id = ensure_dir(_parent_posix(file_path))
		node_id = path_to_id.get(file_path)
		if node_id is None:
			node_id = f"file:{file_path}"
			nodes.append({
				"id": node_id,
				"kind": "file",
				"path": file_path,
				"name": _basename(file_path),
			})
		edges.append({"source": parent_id, "target": node_id, "relation": "contains"})

	return len(dir_created)


def _marker_payload(core_path: str, marker: MarkerEdge) -> dict[str, object]:
	return {
		"core_file": core_path,
		"owner": marker.owner,
		"edit_type": marker.edit_type,
		"line_number": marker.line_number,
		"source_module_id": marker.source_module_id,
		"attribution": marker.attribution,
		"raw_label": marker.raw_label,
		"original_text": marker.original_text,
	}


def build_content_graph(game_repo_root: Path) -> dict[str, object]:
	"""Scan a game checkout and return a JSON-serializable node/edge graph document.

	Modules, master_files overrides, and marker-bearing core files get the specialized `module`/
	`master_file`/`core_file` node kinds with their semantic edges (`master_files_mirror`,
	`marker_edit`), as before. Every other Git-tracked path in the checkout is additionally represented
	as a generic `directory`/`file` node, connected into the same tree via `contains` edges rooted at
	`dir:.` -- so every node has at least one edge, and the full checkout is browsable even where no
	semantic relationship has been extracted.
	"""
	resolved_root = game_repo_root.resolve()
	modules = scan_modules(resolved_root)
	known_module_ids = frozenset(module.id for module in modules)
	master_files = scan_master_files(resolved_root)
	markers_by_path = scan_core_markers(resolved_root, known_module_ids)

	core_paths = {master_file.core_path for master_file in master_files} | set(markers_by_path.keys())

	nodes: list[dict[str, object]] = []
	for module in modules:
		nodes.append({
			"id": _module_node_id(module.owner, module.id),
			"kind": "module",
			"owner": module.owner,
			"module_id": module.id,
			"path": module.path,
			"has_readme": module.has_readme,
		})
	for master_file in master_files:
		nodes.append({
			"id": _master_file_node_id(master_file.owner, master_file.path),
			"kind": "master_file",
			"owner": master_file.owner,
			"path": master_file.path,
			"core_path": master_file.core_path,
		})
	for core_path in sorted(core_paths):
		nodes.append({
			"id": _core_file_node_id(core_path),
			"kind": "core_file",
			"path": core_path,
			"marker_count": len(markers_by_path.get(core_path, ())),
		})

	edges: list[dict[str, object]] = []
	for master_file in master_files:
		edges.append({
			"source": _master_file_node_id(master_file.owner, master_file.path),
			"target": _core_file_node_id(master_file.core_path),
			"relation": "master_files_mirror",
		})

	unresolved_markers: list[dict[str, object]] = []
	marker_count = 0
	for core_path, markers in sorted(markers_by_path.items()):
		for marker in markers:
			marker_count += 1
			if marker.attribution == "exact" and marker.source_module_id is not None:
				edges.append({
					"source": _module_node_id(marker.owner.casefold(), marker.source_module_id),
					"target": _core_file_node_id(core_path),
					"relation": "marker_edit",
					"edit_type": marker.edit_type,
					"attribution": marker.attribution,
					"line_number": marker.line_number,
					"raw_label": marker.raw_label,
					"original_text": marker.original_text,
				})
			else:
				unresolved_markers.append(_marker_payload(core_path, marker))

	path_to_id = {node["path"]: node["id"] for node in nodes if "path" in node}
	tracked_paths = scan_full_tree(resolved_root)
	directory_count = _add_full_tree(nodes, edges, path_to_id, tracked_paths)

	return {
		"nodes": nodes,
		"edges": edges,
		"unresolved_markers": unresolved_markers,
		"counts": {
			"module_count": len(modules),
			"master_files_count": len(master_files),
			"core_file_count": len(core_paths),
			"marker_count": marker_count,
			"unresolved_marker_count": len(unresolved_markers),
			"file_count": len(tracked_paths),
			"directory_count": directory_count,
		},
	}


def _atomic_write(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=path.parent,
		prefix=f"{path.stem}.",
		suffix=".tmp",
	) as temp_file:
		temp_file.write(content)
		temp_file_path = Path(temp_file.name)
	try:
		os.replace(temp_file_path, path)
	except Exception:
		if temp_file_path.exists():
			temp_file_path.unlink()
		raise


def scan_and_cache_content_graph(repo_root: Path, game_repo_root: Path) -> GraphManifest:
	"""Validate the game checkout, scan it, and atomically write the graph cache + manifest."""
	resolved_repo_root = repo_root.resolve()
	resolved_game_root = game_repo_root.resolve()
	validate_game_repository(resolved_game_root)

	graph = build_content_graph(resolved_game_root)
	graph_bytes = canonical_json_bytes(graph)

	try:
		game_revision = repository_revision(resolved_game_root)
	except (OSError, ValueError):
		game_revision = "unknown"

	counts = graph["counts"]
	manifest = GraphManifest(
		snapshot_sha256=sha256_bytes(graph_bytes),
		game_repo_revision=game_revision,
		generated_at=datetime.now(timezone.utc).isoformat(),
		node_count=len(graph["nodes"]),
		edge_count=len(graph["edges"]),
		module_count=counts["module_count"],
		master_files_count=counts["master_files_count"],
		marker_count=counts["marker_count"],
		file_count=counts["file_count"],
		directory_count=counts["directory_count"],
	)

	index_path = resolve_repo_path(resolved_repo_root, GRAPH_INDEX_PATH)
	manifest_path = resolve_repo_path(resolved_repo_root, GRAPH_MANIFEST_PATH)
	_atomic_write(index_path, graph_bytes)
	_atomic_write(manifest_path, canonical_json_bytes(manifest.to_dict()))
	return manifest


def read_graph_cache(repo_root: Path) -> tuple[dict[str, object], GraphManifest] | None:
	"""Return the cached (graph, manifest) pair, or None if no scan has been run yet."""
	resolved_root = repo_root.resolve()
	index_path = resolve_repo_path(resolved_root, GRAPH_INDEX_PATH)
	manifest_path = resolve_repo_path(resolved_root, GRAPH_MANIFEST_PATH)
	if not index_path.is_file() or not manifest_path.is_file():
		return None
	graph = json.loads(index_path.read_text(encoding="utf-8"))
	manifest = GraphManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
	return graph, manifest
