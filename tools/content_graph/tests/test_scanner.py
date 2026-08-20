from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.content_graph.scanner import scan_full_tree


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


if __name__ == "__main__":
	unittest.main()
