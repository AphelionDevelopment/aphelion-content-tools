from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from PIL import Image

from tools.dmi import Dmi
from webapp.server import create_server
from tools.lore_editor.app.manifest import ExportManifest, sha256_bytes
from tools.lore_editor.export import PreparedExport


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


def run_git_allow_fail(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
	return subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)


class StandaloneServerTests(unittest.TestCase):

	def test_server_exposes_local_git_status_and_branch_actions(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "README.md").write_text("initial\n", encoding="utf-8")
			run_git(tool_root, "init", "--initial-branch=main")
			run_git(tool_root, "config", "user.name", "Lore Writer")
			run_git(tool_root, "config", "user.email", "writer@example.invalid")
			run_git(tool_root, "add", "--", "README.md")
			run_git(tool_root, "commit", "-m", "Initial")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/git/status?repository=tool") as response:
					status_payload = json.loads(response.read())
				self.assertEqual("main", status_payload["branch"])
				request = Request(
					f"http://127.0.0.1:{server.server_address[1]}/api/git/branch",
					data=json.dumps({"repository": "tool", "name": "lore/example"}).encode("utf-8"),
					method="POST",
					headers={"Content-Type": "application/json"},
				)
				with urlopen(request) as response:
					self.assertEqual("lore/example", json.loads(response.read())["branch"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_exposes_git_diff_and_github_url_endpoints(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "README.md").write_text("initial\n", encoding="utf-8")
			run_git(tool_root, "init", "--initial-branch=main")
			run_git(tool_root, "config", "user.name", "Lore Writer")
			run_git(tool_root, "config", "user.email", "writer@example.invalid")
			run_git(tool_root, "add", "--", "README.md")
			run_git(tool_root, "commit", "-m", "Initial")
			run_git(tool_root, "remote", "add", "origin", "https://github.com/AphelionDevelopment/Meridian-Rift.git")
			(tool_root / "README.md").write_text("changed\n", encoding="utf-8")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/git/diff?repository=tool&path=README.md") as response:
					diff_payload = json.loads(response.read())
				self.assertIn("+changed", diff_payload["diff"])

				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/git/github-url?repository=tool&path=README.md") as response:
					url_payload = json.loads(response.read())
				self.assertTrue(url_payload["url"].startswith("https://github.com/AphelionDevelopment/Meridian-Rift/blob/"))
				self.assertTrue(url_payload["url"].endswith("/README.md"))
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_open_file_endpoint_dispatches_to_editor_or_explorer(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "README.md").write_text("initial\n", encoding="utf-8")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with patch("webapp.git_adapter.os.startfile", create=True) as startfile:
					request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/git/open-file",
						data=json.dumps({"repository": "tool", "path": "README.md", "target": "editor"}).encode("utf-8"),
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with urlopen(request) as response:
						self.assertTrue(json.loads(response.read())["opened"])
				startfile.assert_called_once()

				with patch("webapp.git_adapter.subprocess.Popen") as popen:
					request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/git/open-file",
						data=json.dumps({"repository": "tool", "path": "README.md", "target": "explorer"}).encode("utf-8"),
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with urlopen(request) as response:
						self.assertTrue(json.loads(response.read())["opened"])
				popen.assert_called_once()
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_uses_separate_game_checkout_for_icon_assets(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(game_root / "icons").mkdir(parents=True)
			dmi = Dmi(32, 32)
			state = dmi.state("radio")
			state.frame(Image.new("RGBA", (32, 32), (255, 0, 0, 255)))
			dmi.to_file(game_root / "icons/radio.dmi")

			server = create_server(tool_root, 0, game_repo_root=game_root)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/icon-files") as response:
					payload = json.loads(response.read())
				self.assertEqual(["icons/radio.dmi"], payload["files"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_reports_health_and_serves_the_catalog_on_startup(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text(json.dumps([{
				"type_path": "/obj/item/radio",
				"label": "radio",
				"field_profile": "atom_like",
				"base_values": {"name": "radio", "description": "A standard radio."},
			}]), encoding="utf-8")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/health") as response:
					health_payload = json.loads(response.read())
				self.assertEqual({"ok": True, "service": "aphelion-content-tools"}, health_payload)

				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/catalog") as response:
					catalog_payload = json.loads(response.read())
				self.assertEqual(["/obj/item/radio"], [target["type_path"] for target in catalog_payload["targets"]])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_reports_git_conflict_status_through_the_api(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			run_git(tool_root, "init", "--initial-branch=main")
			run_git(tool_root, "config", "user.name", "Lore Writer")
			run_git(tool_root, "config", "user.email", "writer@example.invalid")
			(tool_root / "shared.txt").write_text("base\n", encoding="utf-8")
			run_git(tool_root, "add", "--", "shared.txt")
			run_git(tool_root, "commit", "-m", "Add shared file")
			run_git(tool_root, "switch", "--create", "conflicting-branch")
			(tool_root / "shared.txt").write_text("branch change\n", encoding="utf-8")
			run_git(tool_root, "commit", "-am", "Branch change")
			run_git(tool_root, "switch", "main")
			(tool_root / "shared.txt").write_text("main change\n", encoding="utf-8")
			run_git(tool_root, "commit", "-am", "Main change")
			merge_result = run_git_allow_fail(tool_root, "merge", "conflicting-branch")
			self.assertNotEqual(0, merge_result.returncode)

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/git/status?repository=tool") as response:
					status_payload = json.loads(response.read())
				self.assertTrue(status_payload["conflicted"])
				self.assertIn("shared.txt", status_payload["conflict_files"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_commit_endpoint_commits_requested_paths_and_reports_remaining_dirty_files(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			run_git(tool_root, "init", "--initial-branch=main")
			run_git(tool_root, "config", "user.name", "Lore Writer")
			run_git(tool_root, "config", "user.email", "writer@example.invalid")
			(tool_root / "README.md").write_text("initial\n", encoding="utf-8")
			run_git(tool_root, "add", "--", "README.md")
			run_git(tool_root, "commit", "-m", "Initial")
			(tool_root / "lore.json").write_text("lore\n", encoding="utf-8")
			(tool_root / "unrelated.txt").write_text("leave pending\n", encoding="utf-8")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				commit_request = Request(
					f"http://127.0.0.1:{server.server_address[1]}/api/git/commit",
					data=json.dumps({"repository": "tool", "paths": ["lore.json"], "message": "Update lore"}).encode("utf-8"),
					method="POST",
					headers={"Content-Type": "application/json"},
				)
				with urlopen(commit_request) as response:
					commit_payload = json.loads(response.read())
				self.assertTrue(commit_payload["commit"])

				with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/git/status?repository=tool") as response:
					status_payload = json.loads(response.read())
				self.assertEqual(["unrelated.txt"], status_payload["changed_files"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_open_in_github_desktop_endpoint_reports_missing_launcher(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			run_git(tool_root, "init", "--initial-branch=main")
			run_git(tool_root, "config", "user.name", "Lore Writer")
			run_git(tool_root, "config", "user.email", "writer@example.invalid")
			(tool_root / "README.md").write_text("initial\n", encoding="utf-8")
			run_git(tool_root, "add", "--", "README.md")
			run_git(tool_root, "commit", "-m", "Initial")

			server = create_server(tool_root, 0)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with patch("webapp.git_adapter.find_github_desktop_launcher", return_value=None):
					open_request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/git/open",
						data=json.dumps({"repository": "tool"}).encode("utf-8"),
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with self.assertRaises(HTTPError) as context:
						urlopen(open_request)
					self.assertEqual(400, context.exception.code)
					error_payload = json.loads(context.exception.read())
					self.assertIn("GitHub Desktop", error_payload["error"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_export_apply_endpoint_refuses_when_game_checkout_is_dirty(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			for repo_root in (tool_root, game_root):
				repo_root.mkdir(parents=True)
				run_git(repo_root, "init", "--initial-branch=main")
				run_git(repo_root, "config", "user.name", "Lore Writer")
				run_git(repo_root, "config", "user.email", "writer@example.invalid")
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text("[]", encoding="utf-8")
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
			artifact.parent.mkdir(parents=True)
			artifact.write_text("old\n", encoding="utf-8")
			run_git(tool_root, "add", "--all")
			run_git(tool_root, "commit", "-m", "Tool source")
			run_git(game_root, "add", "--all")
			run_git(game_root, "commit", "-m", "Game source")
			before = artifact.read_bytes()

			server = create_server(tool_root, 0, game_repo_root=game_root)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				prepare_request = Request(
					f"http://127.0.0.1:{server.server_address[1]}/api/export/prepare",
					data=b"{}",
					method="POST",
					headers={"Content-Type": "application/json"},
				)
				with urlopen(prepare_request) as response:
					prepare_payload = json.loads(response.read())
				self.assertTrue(prepare_payload["prepared"])

				(game_root / "uncommitted.txt").write_text("pending\n", encoding="utf-8")

				apply_request = Request(
					f"http://127.0.0.1:{server.server_address[1]}/api/export/apply",
					data=json.dumps({"stage": prepare_payload["stage"]}).encode("utf-8"),
					method="POST",
					headers={"Content-Type": "application/json"},
				)
				with self.assertRaises(HTTPError) as context:
					urlopen(apply_request)
				self.assertEqual(400, context.exception.code)
				error_payload = json.loads(context.exception.read())
				self.assertIn("uncommitted changes", error_payload["error"])
				self.assertEqual(before, artifact.read_bytes())
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_exposes_prepare_and_apply_export_actions(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/stages/example").mkdir(parents=True)
			manifest = ExportManifest(
				tool_repo_revision="tool-sha",
				tool_branch="main",
				catalog_sha256=sha256_bytes(b"catalog"),
				game_repo_revision="game-sha",
				entry_ids=(),
				type_paths=(),
				generated_artifact_sha256=sha256_bytes(b"artifact"),
			)
			prepared = PreparedExport(
				directory=tool_root / "tools/lore_editor/stages/example",
				artifact_path=tool_root / "tools/lore_editor/stages/example/artifact.dm",
				manifest=manifest,
			)
			server = create_server(tool_root, 0, game_repo_root=game_root)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with patch("tools.lore_editor.export.prepare_export", return_value=prepared) as prepare, patch(
					"tools.lore_editor.export.apply_export", return_value=game_root / "artifact.dm"
				) as apply:
					prepare_request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/export/prepare",
						data=b"{}",
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with urlopen(prepare_request) as response:
						prepare_payload = json.loads(response.read())
					self.assertTrue(prepare_payload["prepared"])
					prepare.assert_called_once_with(
						tool_root.resolve(),
						game_root.resolve(),
						(tool_root / "tools/lore_editor/stages").resolve(),
					)

					apply_request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/export/apply",
						data=json.dumps({"stage": "example"}).encode("utf-8"),
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with urlopen(apply_request) as response:
						apply_payload = json.loads(response.read())
					self.assertTrue(apply_payload["applied"])
					apply.assert_called_once_with(
						(tool_root / "tools/lore_editor/stages/example").resolve(),
						game_root.resolve(),
					)
					self.assertFalse(apply_payload["opened_in_github_desktop"])
					self.assertIsNotNone(apply_payload["github_desktop_error"])
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)

	def test_server_export_apply_endpoint_opens_github_desktop_for_the_game_checkout_on_success(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			game_root.mkdir(parents=True)
			(tool_root / "tools/lore_editor/stages/example").mkdir(parents=True)
			manifest = ExportManifest(
				tool_repo_revision="tool-sha",
				tool_branch="main",
				catalog_sha256=sha256_bytes(b"catalog"),
				game_repo_revision="game-sha",
				entry_ids=(),
				type_paths=(),
				generated_artifact_sha256=sha256_bytes(b"artifact"),
			)
			prepared = PreparedExport(
				directory=tool_root / "tools/lore_editor/stages/example",
				artifact_path=tool_root / "tools/lore_editor/stages/example/artifact.dm",
				manifest=manifest,
			)
			server = create_server(tool_root, 0, game_repo_root=game_root)
			thread = threading.Thread(target=server.serve_forever, daemon=True)
			thread.start()
			try:
				with patch("tools.lore_editor.export.apply_export", return_value=game_root / "artifact.dm"), patch(
					"webapp.git_adapter.find_github_desktop_launcher", return_value="github.bat",
				), patch("webapp.git_adapter.subprocess.Popen") as popen:
					apply_request = Request(
						f"http://127.0.0.1:{server.server_address[1]}/api/export/apply",
						data=json.dumps({"stage": "example"}).encode("utf-8"),
						method="POST",
						headers={"Content-Type": "application/json"},
					)
					with urlopen(apply_request) as response:
						apply_payload = json.loads(response.read())
					self.assertTrue(apply_payload["applied"])
					self.assertTrue(apply_payload["opened_in_github_desktop"])
					self.assertIsNone(apply_payload["github_desktop_error"])
					popen.assert_called_once()
					self.assertEqual(
						["cmd.exe", "/d", "/c", "github.bat", str(game_root.resolve())],
						popen.call_args.args[0],
					)
			finally:
				server.shutdown()
				server.server_close()
				thread.join(timeout=2)


if __name__ == "__main__":
	unittest.main()
