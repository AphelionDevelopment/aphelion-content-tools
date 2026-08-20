from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tools.content_graph.graph import build_content_graph
from tools.content_graph.queries import edits_for_core_file, modules_missing_readme, unresolved_markers

from tools.content_graph.tests.test_graph import make_fixture_game_repo


class ContentGraphQueryTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		game_root = Path(self.temp_dir.name) / "game"
		make_fixture_game_repo(game_root)
		self.graph = build_content_graph(game_root)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_edits_for_core_file_returns_the_resolved_marker(self) -> None:
		edits = edits_for_core_file(self.graph, "code/modules/shuttle/shuttle.dm")

		self.assertEqual(1, len(edits))
		self.assertTrue(edits[0]["resolved"])
		self.assertEqual("module:nova:shuttle_toggle", edits[0]["source"])

	def test_edits_for_core_file_returns_the_unresolved_marker(self) -> None:
		edits = edits_for_core_file(self.graph, "code/modules/other/other.dm")

		self.assertEqual(1, len(edits))
		self.assertFalse(edits[0]["resolved"])
		self.assertEqual("unattributed", edits[0]["attribution"])

	def test_edits_for_core_file_returns_empty_list_for_untouched_file(self) -> None:
		self.assertEqual([], edits_for_core_file(self.graph, "code/modules/untouched/untouched.dm"))

	def test_modules_missing_readme_returns_only_the_module_without_one(self) -> None:
		missing = modules_missing_readme(self.graph)

		self.assertEqual(1, len(missing))
		self.assertEqual("no_readme_module", missing[0]["module_id"])

	def test_unresolved_markers_matches_the_graphs_own_list(self) -> None:
		self.assertEqual(self.graph["unresolved_markers"], unresolved_markers(self.graph))


if __name__ == "__main__":
	unittest.main()
