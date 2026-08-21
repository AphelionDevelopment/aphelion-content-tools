from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from tools.lore_editor.api import find_type_definition


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


class FindTypeDefinitionTests(unittest.TestCase):
	def make_game_repo(self) -> Path:
		temp_dir = TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		repo_root = Path(temp_dir.name)
		run_git(repo_root, "init", "--initial-branch=main")
		run_git(repo_root, "config", "user.name", "Writer")
		run_git(repo_root, "config", "user.email", "writer@example.invalid")
		(repo_root / "code").mkdir()
		(repo_root / "code" / "items.dm").write_text(
			"/obj/item/radio\n\tname = \"radio\"\n\ticon = 'icons/obj/radio.dmi'\n\n/obj/item/megaphone\n\tname = \"megaphone\"\n",
			encoding="utf-8",
		)
		run_git(repo_root, "add", "--all")
		run_git(repo_root, "commit", "-m", "Initial")
		return repo_root

	def test_finds_the_definition_line_for_a_known_type_path(self) -> None:
		repo_root = self.make_game_repo()

		definition = find_type_definition(repo_root, "/obj/item/megaphone")

		self.assertEqual({"path": "code/items.dm", "line": 5}, definition)

	def test_returns_none_for_an_unknown_type_path(self) -> None:
		repo_root = self.make_game_repo()

		self.assertIsNone(find_type_definition(repo_root, "/obj/item/nonexistent"))

	def test_escapes_regex_special_characters_in_the_type_path(self) -> None:
		repo_root = self.make_game_repo()
		(repo_root / "code" / "weird.dm").write_text("/obj/item/weird.name\n\tname = \"weird\"\n", encoding="utf-8")
		run_git(repo_root, "add", "--all")
		run_git(repo_root, "commit", "-m", "Add weird type")

		definition = find_type_definition(repo_root, "/obj/item/weird.name")

		self.assertEqual({"path": "code/weird.dm", "line": 1}, definition)
		# A literal dot must not act as a regex wildcard and match the unrelated "weirdXname" type below.
		(repo_root / "code" / "weird.dm").write_text(
			"/obj/item/weird.name\n\tname = \"weird\"\n/obj/item/weirdXname\n\tname = \"other\"\n",
			encoding="utf-8",
		)
		run_git(repo_root, "add", "--all")
		run_git(repo_root, "commit", "-m", "Add decoy type")
		self.assertEqual({"path": "code/weird.dm", "line": 1}, find_type_definition(repo_root, "/obj/item/weird.name"))


if __name__ == "__main__":
	unittest.main()
