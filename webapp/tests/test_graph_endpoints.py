from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, urlopen

from tools.content_graph.graph import scan_and_cache_content_graph
from tools.content_graph.tests.test_graph import make_fixture_game_repo
from webapp.server import create_server


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


class GraphQueryEndpointTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = TemporaryDirectory()
		root = Path(self.temp_dir.name)
		self.tool_root = root / "tool"
		self.game_root = root / "game"
		(self.tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
		make_fixture_game_repo(self.game_root)
		run_git(self.game_root, "init", "--initial-branch=main")
		run_git(self.game_root, "config", "user.name", "Writer")
		run_git(self.game_root, "config", "user.email", "writer@example.invalid")
		run_git(self.game_root, "remote", "add", "origin", "https://github.com/AphelionDevelopment/Meridian-Rift.git")
		run_git(self.game_root, "add", "--all")
		run_git(self.game_root, "commit", "-m", "Initial")
		scan_and_cache_content_graph(self.tool_root, self.game_root)

		self.server = create_server(self.tool_root, 0, game_repo_root=self.game_root)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()
		self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

	def tearDown(self) -> None:
		self.server.shutdown()
		self.server.server_close()
		self.thread.join(timeout=2)
		self.temp_dir.cleanup()

	def test_edits_endpoint_returns_the_resolved_and_unresolved_markers_for_a_core_file(self) -> None:
		with urlopen(f"{self.base_url}/api/graph/edits?core_file=code/modules/shuttle/shuttle.dm") as response:
			payload = json.loads(response.read())

		self.assertTrue(payload["scanned"])
		self.assertEqual(1, len(payload["edits"]))
		self.assertTrue(payload["edits"][0]["resolved"])

	def test_edits_endpoint_requires_a_core_file_parameter(self) -> None:
		from urllib.error import HTTPError

		with self.assertRaises(HTTPError) as context:
			urlopen(f"{self.base_url}/api/graph/edits")
		self.assertEqual(400, context.exception.code)

	def test_modules_endpoint_filters_to_modules_missing_a_readme(self) -> None:
		with urlopen(f"{self.base_url}/api/graph/modules?missing_readme=true") as response:
			payload = json.loads(response.read())

		self.assertEqual(["no_readme_module"], [module["module_id"] for module in payload["modules"]])

	def test_modules_endpoint_returns_all_modules_by_default(self) -> None:
		with urlopen(f"{self.base_url}/api/graph/modules") as response:
			payload = json.loads(response.read())

		self.assertEqual(2, len(payload["modules"]))

	def test_unresolved_endpoint_returns_the_graphs_unresolved_markers(self) -> None:
		with urlopen(f"{self.base_url}/api/graph/unresolved") as response:
			payload = json.loads(response.read())

		self.assertEqual(1, len(payload["unresolved_markers"]))
		self.assertEqual("code/modules/other/other.dm", payload["unresolved_markers"][0]["core_file"])

	def test_marker_history_endpoint_returns_the_commit_that_introduced_the_line(self) -> None:
		with urlopen(f"{self.base_url}/api/graph/marker-history?core_file=code/modules/other/other.dm&line=2") as response:
			payload = json.loads(response.read())

		self.assertEqual(1, len(payload["commits"]))
		self.assertEqual("Initial", payload["commits"][0]["subject"])
		self.assertIn("+\t// NOVA EDIT ADDITION - some future module", payload["commits"][0]["diff"])

	def test_marker_history_endpoint_requires_core_file_and_line(self) -> None:
		from urllib.error import HTTPError

		with self.assertRaises(HTTPError) as context:
			urlopen(f"{self.base_url}/api/graph/marker-history?line=2")
		self.assertEqual(400, context.exception.code)

	def test_markers_edit_endpoint_rewrites_the_marker_label(self) -> None:
		other_dm = self.game_root / "code" / "modules" / "other" / "other.dm"
		request = Request(
			f"{self.base_url}/api/graph/markers/edit",
			data=json.dumps({
				"core_file": "code/modules/other/other.dm",
				"line_number": 2,
				"expected_line": "\t// NOVA EDIT ADDITION - some future module",
				"new_label": "shuttle_toggle",
			}).encode("utf-8"),
			method="POST",
			headers={"Content-Type": "application/json"},
		)

		with urlopen(request) as response:
			payload = json.loads(response.read())

		self.assertTrue(payload["edited"])
		self.assertIn("\t// NOVA EDIT ADDITION - shuttle_toggle\n", other_dm.read_text(encoding="utf-8"))

	def test_markers_edit_endpoint_refuses_a_stale_expected_line(self) -> None:
		from urllib.error import HTTPError

		request = Request(
			f"{self.base_url}/api/graph/markers/edit",
			data=json.dumps({
				"core_file": "code/modules/other/other.dm",
				"line_number": 2,
				"expected_line": "not what is actually there",
				"new_label": "shuttle_toggle",
			}).encode("utf-8"),
			method="POST",
			headers={"Content-Type": "application/json"},
		)

		with self.assertRaises(HTTPError) as context:
			urlopen(request)
		self.assertEqual(400, context.exception.code)


if __name__ == "__main__":
	unittest.main()
