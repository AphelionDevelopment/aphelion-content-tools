from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.content_graph.graph import (
	build_content_graph,
	read_graph_cache,
	scan_and_cache_content_graph,
)


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


def make_fixture_game_repo(game_root: Path) -> None:
	game_root.mkdir(parents=True)
	(game_root / "tgstation.dme").write_text("", encoding="utf-8")

	module_dir = game_root / "modular_nova" / "modules" / "shuttle_toggle" / "code"
	module_dir.mkdir(parents=True)
	(module_dir / "shuttle_toggle.dm").write_text(
		"/obj/docking_port/shuttle_toggle\n"
		"// See modular_nova/modules/no_readme_module for related config.\n",
		encoding="utf-8",
	)
	(game_root / "modular_nova" / "modules" / "shuttle_toggle" / "readme.md").write_text("# Shuttle toggle\n", encoding="utf-8")

	# a module with no readme.md
	(game_root / "modular_nova" / "modules" / "no_readme_module" / "code").mkdir(parents=True)

	master_files_root = game_root / "modular_nova" / "master_files" / "code" / "modules" / "shuttle"
	master_files_root.mkdir(parents=True)
	(master_files_root / "shuttle.dm").write_text("/obj/docking_port\n", encoding="utf-8")

	core_file = game_root / "code" / "modules" / "shuttle" / "shuttle.dm"
	core_file.parent.mkdir(parents=True)
	core_file.write_text(
		"/obj/docking_port\n"
		"\t// NOVA EDIT ADDITION START - SHUTTLE_TOGGLE - allow manual recall\n"
		"\tvar/adminEmergencyNoRecall = FALSE\n"
		"\t// NOVA EDIT ADDITION END\n",
		encoding="utf-8",
	)

	# a core file with an unresolved marker (references a module that doesn't exist)
	other_core_file = game_root / "code" / "modules" / "other" / "other.dm"
	other_core_file.parent.mkdir(parents=True)
	other_core_file.write_text(
		"/obj/item/other\n"
		"\t// NOVA EDIT ADDITION - some future module\n"
		"\t// Also touches code/modules/shuttle/shuttle.dm\n",
		encoding="utf-8",
	)

	# non-modular repo content -- not a module, master_files override, or marker-bearing core file
	(game_root / ".github" / "workflows").mkdir(parents=True)
	(game_root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
	(game_root / "README.md").write_text("# Meridian-Rift\n", encoding="utf-8")
	(game_root / "icons" / "obj").mkdir(parents=True)
	(game_root / "icons" / "obj" / "example.dmi").write_text("", encoding="utf-8")


class ContentGraphScanTests(unittest.TestCase):
	def test_build_content_graph_produces_expected_nodes_and_edges(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_fixture_game_repo(game_root)

			graph = build_content_graph(game_root)

		node_kinds = [node["kind"] for node in graph["nodes"]]
		self.assertEqual(2, node_kinds.count("module"))
		self.assertEqual(1, node_kinds.count("master_file"))
		self.assertEqual(2, node_kinds.count("core_file"))

		module_ids = {node["id"] for node in graph["nodes"] if node["kind"] == "module"}
		self.assertIn("module:nova:shuttle_toggle", module_ids)
		self.assertIn("module:nova:no_readme_module", module_ids)

		readme_flags = {node["module_id"]: node["has_readme"] for node in graph["nodes"] if node["kind"] == "module"}
		self.assertTrue(readme_flags["shuttle_toggle"])
		self.assertFalse(readme_flags["no_readme_module"])

		mirror_edges = [edge for edge in graph["edges"] if edge["relation"] == "master_files_mirror"]
		self.assertEqual(1, len(mirror_edges))
		self.assertEqual("core_file:code/modules/shuttle/shuttle.dm", mirror_edges[0]["target"])

		marker_edges = [edge for edge in graph["edges"] if edge["relation"] == "marker_edit"]
		self.assertEqual(1, len(marker_edges))
		self.assertEqual("module:nova:shuttle_toggle", marker_edges[0]["source"])
		self.assertEqual("core_file:code/modules/shuttle/shuttle.dm", marker_edges[0]["target"])
		self.assertEqual("addition", marker_edges[0]["edit_type"])

		self.assertEqual(1, len(graph["unresolved_markers"]))
		self.assertEqual("code/modules/other/other.dm", graph["unresolved_markers"][0]["core_file"])
		self.assertEqual("unattributed", graph["unresolved_markers"][0]["attribution"])

		self.assertEqual(2, graph["counts"]["module_count"])
		self.assertEqual(1, graph["counts"]["master_files_count"])
		self.assertEqual(2, graph["counts"]["marker_count"])
		self.assertEqual(1, graph["counts"]["unresolved_marker_count"])

		module_reference_edges = [edge for edge in graph["edges"] if edge["relation"] == "module_reference"]
		self.assertEqual(1, len(module_reference_edges))
		self.assertEqual("module:nova:shuttle_toggle", module_reference_edges[0]["source"])
		self.assertEqual("module:nova:no_readme_module", module_reference_edges[0]["target"])

		core_reference_edges = [edge for edge in graph["edges"] if edge["relation"] == "core_reference"]
		self.assertEqual(1, len(core_reference_edges))
		self.assertEqual("core_file:code/modules/other/other.dm", core_reference_edges[0]["source"])
		self.assertEqual("core_file:code/modules/shuttle/shuttle.dm", core_reference_edges[0]["target"])

		self.assertEqual(2, graph["counts"]["reference_count"])

		module_nodes = {node["module_id"]: node for node in graph["nodes"] if node["kind"] == "module"}
		self.assertEqual(1, module_nodes["shuttle_toggle"]["file_count"])
		self.assertGreater(module_nodes["shuttle_toggle"]["total_bytes"], 0)
		self.assertEqual(0, module_nodes["no_readme_module"]["file_count"])

		core_file_nodes = {node["path"]: node for node in graph["nodes"] if node["kind"] == "core_file"}
		self.assertIsNotNone(core_file_nodes["code/modules/shuttle/shuttle.dm"]["size_bytes"])
		self.assertGreater(core_file_nodes["code/modules/shuttle/shuttle.dm"]["line_count"], 0)

		master_file_nodes = [node for node in graph["nodes"] if node["kind"] == "master_file"]
		self.assertIsNotNone(master_file_nodes[0]["size_bytes"])

	def test_full_tree_connects_every_tracked_file_without_duplicating_specialized_nodes(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_fixture_game_repo(game_root)

			graph = build_content_graph(game_root)

		nodes_by_id = {node["id"]: node for node in graph["nodes"]}
		self.assertIn("dir:.", nodes_by_id)
		self.assertEqual("directory", nodes_by_id["dir:."]["kind"])

		# non-modular content becomes generic file/directory nodes
		self.assertIn("file:README.md", nodes_by_id)
		self.assertIn("file:.github/workflows/ci.yml", nodes_by_id)
		self.assertIn("dir:.github/workflows", nodes_by_id)
		self.assertIn("file:icons/obj/example.dmi", nodes_by_id)

		# every path is reachable from the root via exactly one parent "contains" edge
		contains_edges = [edge for edge in graph["edges"] if edge["relation"] == "contains"]
		parent_by_child = {edge["target"]: edge["source"] for edge in contains_edges}
		self.assertIn("file:README.md", parent_by_child)
		self.assertEqual("dir:.", parent_by_child["file:README.md"])
		self.assertIn("dir:.github", parent_by_child)

		# module/master_file/core_file paths are wired into the tree, not duplicated as file:/dir: nodes
		self.assertIn("module:nova:shuttle_toggle", parent_by_child)
		self.assertNotIn("dir:modular_nova/modules/shuttle_toggle", nodes_by_id)
		self.assertIn("core_file:code/modules/shuttle/shuttle.dm", parent_by_child)
		self.assertNotIn("file:code/modules/shuttle/shuttle.dm", nodes_by_id)

		self.assertGreater(graph["counts"]["file_count"], 0)
		self.assertGreater(graph["counts"]["directory_count"], 0)

	def test_scan_and_cache_writes_atomically_readable_cache(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			make_fixture_game_repo(game_root)
			run_git(game_root, "init", "--initial-branch=main")
			run_git(game_root, "config", "user.name", "Writer")
			run_git(game_root, "config", "user.email", "writer@example.invalid")
			run_git(game_root, "add", "--all")
			run_git(game_root, "commit", "-m", "Initial")

			manifest = scan_and_cache_content_graph(tool_root, game_root)

			self.assertEqual(2, manifest.module_count)
			self.assertEqual(1, manifest.master_files_count)
			self.assertEqual(2, manifest.marker_count)
			self.assertGreater(manifest.file_count, 0)
			self.assertGreater(manifest.directory_count, 0)
			self.assertNotEqual("unknown", manifest.game_repo_revision)

			cached = read_graph_cache(tool_root)
			self.assertIsNotNone(cached)
			graph, cached_manifest = cached
			self.assertEqual(manifest.snapshot_sha256, cached_manifest.snapshot_sha256)
			self.assertEqual(2, len([node for node in graph["nodes"] if node["kind"] == "module"]))

			index_path = tool_root / "tools/content_graph/cache/index.json"
			manifest_path = tool_root / "tools/content_graph/cache/manifest.json"
			self.assertTrue(index_path.is_file())
			self.assertTrue(manifest_path.is_file())
			json.loads(index_path.read_text(encoding="utf-8"))
			json.loads(manifest_path.read_text(encoding="utf-8"))

	def test_read_graph_cache_returns_none_when_never_scanned(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			tool_root = Path(temp_dir)
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)

			self.assertIsNone(read_graph_cache(tool_root))

	def test_scan_rejects_game_repository_missing_marker_file(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			game_root.mkdir(parents=True)

			with self.assertRaisesRegex(ValueError, "does not look like a Meridian-Rift checkout"):
				scan_and_cache_content_graph(tool_root, game_root)


if __name__ == "__main__":
	unittest.main()
