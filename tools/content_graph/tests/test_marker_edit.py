from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from webapp.git_adapter import RepositoryStatus
from tools.content_graph.marker_edit import apply_marker_label_edit


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


def make_repo(repo_root: Path) -> None:
	repo_root.mkdir(parents=True)
	run_git(repo_root, "init", "--initial-branch=main")
	run_git(repo_root, "config", "user.name", "Writer")
	run_git(repo_root, "config", "user.email", "writer@example.invalid")
	core_file = repo_root / "code" / "modules" / "other" / "other.dm"
	core_file.parent.mkdir(parents=True)
	core_file.write_text(
		"/obj/item/other\n"
		"\t// NOVA EDIT ADDITION - some future module\n",
		encoding="utf-8",
	)
	run_git(repo_root, "add", "--all")
	run_git(repo_root, "commit", "-m", "Initial")


class ApplyMarkerLabelEditTests(unittest.TestCase):
	def test_rewrites_the_marker_line_in_place(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)
			core_file = game_root / "code" / "modules" / "other" / "other.dm"

			apply_marker_label_edit(
				game_root,
				"code/modules/other/other.dm",
				2,
				"\t// NOVA EDIT ADDITION - some future module",
				"shuttle_toggle",
			)

			content = core_file.read_text(encoding="utf-8")
			self.assertIn("\t// NOVA EDIT ADDITION - shuttle_toggle\n", content)
			self.assertIn("/obj/item/other\n", content)

	def test_refuses_when_the_line_no_longer_matches_expected_line(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)

			with self.assertRaisesRegex(ValueError, "changed since this marker was loaded"):
				apply_marker_label_edit(
					game_root,
					"code/modules/other/other.dm",
					2,
					"\t// NOVA EDIT ADDITION - a stale expectation",
					"shuttle_toggle",
				)

	def test_refuses_a_line_number_beyond_the_end_of_the_file(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)

			with self.assertRaises(ValueError):
				apply_marker_label_edit(game_root, "code/modules/other/other.dm", 999, "anything", "shuttle_toggle")

	def test_refuses_an_empty_new_label(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)

			with self.assertRaises(ValueError):
				apply_marker_label_edit(
					game_root,
					"code/modules/other/other.dm",
					2,
					"\t// NOVA EDIT ADDITION - some future module",
					"   ",
				)

	def test_refuses_when_the_game_checkout_has_git_conflicts(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)
			conflicted_status = RepositoryStatus(
				branch="main",
				upstream=None,
				ahead=0,
				behind=0,
				dirty=True,
				changed_files=(),
				conflict_files=("code/modules/other/other.dm",),
			)

			with patch("tools.content_graph.marker_edit.repository_status", return_value=conflicted_status):
				with self.assertRaisesRegex(ValueError, "unresolved Git conflicts"):
					apply_marker_label_edit(
						game_root,
						"code/modules/other/other.dm",
						2,
						"\t// NOVA EDIT ADDITION - some future module",
						"shuttle_toggle",
					)

	def test_refuses_a_line_that_is_not_a_recognizable_marker(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir) / "game"
			make_repo(game_root)

			with self.assertRaises(ValueError):
				apply_marker_label_edit(game_root, "code/modules/other/other.dm", 1, "/obj/item/other", "shuttle_toggle")


if __name__ == "__main__":
	unittest.main()
