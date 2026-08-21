from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.content_graph.scanner import ModuleNode, scan_core_file_texts, scan_full_tree, scan_module_file_texts


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


class ScanFullTreeTests(unittest.TestCase):
	def test_scan_full_tree_uses_git_ls_files_when_available(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			run_git(repo_root, "init", "--initial-branch=main")
			run_git(repo_root, "config", "user.name", "Writer")
			run_git(repo_root, "config", "user.email", "writer@example.invalid")
			(repo_root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
			(repo_root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
			run_git(repo_root, "add", "--", "tracked.txt")
			run_git(repo_root, "commit", "-m", "Initial")

			self.assertEqual(("tracked.txt",), scan_full_tree(repo_root))

	def test_scan_full_tree_falls_back_without_git(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			(repo_root / "code").mkdir()
			(repo_root / "code" / "file.dm").write_text("", encoding="utf-8")
			(repo_root / "root.txt").write_text("", encoding="utf-8")
			(repo_root / "__pycache__").mkdir()
			(repo_root / "__pycache__" / "cached.pyc").write_text("", encoding="utf-8")

			self.assertEqual(("code/file.dm", "root.txt"), scan_full_tree(repo_root))


class ScanModuleFileTextsTests(unittest.TestCase):
	def test_reads_marker_suffixed_files_and_reports_size_and_count(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)
			module_root = game_root / "modular_nova" / "modules" / "example" / "code"
			module_root.mkdir(parents=True)
			(module_root / "a.dm").write_text("/obj/item/a\n", encoding="utf-8")
			(module_root / "b.dmm").write_text("/obj/item/b\n", encoding="utf-8")
			(module_root / "ignored.txt").write_text("not a marker suffix\n", encoding="utf-8")
			module = ModuleNode(id="example", owner="nova", path="modular_nova/modules/example", has_readme=False)

			contents = scan_module_file_texts(game_root, (module,))

			content = contents["modular_nova/modules/example"]
			self.assertEqual(2, content.file_count)
			self.assertIn("/obj/item/a", content.text)
			self.assertIn("/obj/item/b", content.text)
			self.assertNotIn("not a marker suffix", content.text)
			self.assertGreater(content.total_bytes, 0)


class ScanCoreFileTextsTests(unittest.TestCase):
	def test_reads_only_the_given_paths_and_counts_lines(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)
			(game_root / "code").mkdir()
			(game_root / "code" / "a.dm").write_text("line one\nline two\n", encoding="utf-8", newline="")
			(game_root / "code" / "b.dm").write_text("untouched\n", encoding="utf-8", newline="")

			contents = scan_core_file_texts(game_root, frozenset({"code/a.dm"}))

			self.assertEqual(("code/a.dm",), tuple(contents.keys()))
			self.assertEqual(2, contents["code/a.dm"].line_count)
			self.assertEqual(len("line one\nline two\n".encode("utf-8")), contents["code/a.dm"].size_bytes)

	def test_skips_a_path_that_does_not_exist(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)

			contents = scan_core_file_texts(game_root, frozenset({"code/missing.dm"}))

			self.assertEqual({}, contents)


if __name__ == "__main__":
	unittest.main()
