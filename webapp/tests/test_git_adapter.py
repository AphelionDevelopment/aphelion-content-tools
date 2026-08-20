from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import threading
import unittest
from unittest.mock import patch

from webapp import git_adapter
from webapp.git_adapter import (
	GitAdapterError,
	create_branch,
	list_tracked_files,
	open_in_github_desktop,
	repository_remote_url,
	repository_status,
	stage_and_commit,
)


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


def run_git_allow_fail(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
	return subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, text=True)


def clone_repo(source: Path, destination: Path) -> None:
	subprocess.run(["git", "clone", str(source), str(destination)], check=True, capture_output=True, text=True)
	run_git(destination, "config", "user.name", "Lore Writer")
	run_git(destination, "config", "user.email", "writer@example.invalid")


class GitAdapterTests(unittest.TestCase):

	def make_repo(self) -> tuple[TemporaryDirectory[str], Path]:
		temporary_directory = TemporaryDirectory()
		repo_root = Path(temporary_directory.name)
		run_git(repo_root, "init", "--initial-branch=main")
		run_git(repo_root, "config", "user.name", "Lore Writer")
		run_git(repo_root, "config", "user.email", "writer@example.invalid")
		(repo_root / "README.md").write_text("initial\n", encoding="utf-8")
		run_git(repo_root, "add", "--", "README.md")
		run_git(repo_root, "commit", "-m", "Initial")
		return temporary_directory, repo_root

	def test_status_reports_branch_dirty_files_and_conflicts(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "change.txt").write_text("pending\n", encoding="utf-8")

		status = repository_status(repo_root)

		self.assertEqual("main", status.branch)
		self.assertTrue(status.dirty)
		self.assertEqual(("change.txt",), status.changed_files)
		self.assertFalse(status.conflicted)

	def test_status_does_not_treat_staged_additions_as_conflicts(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "added.txt").write_text("added\n", encoding="utf-8")
		run_git(repo_root, "add", "--", "added.txt")

		status = repository_status(repo_root)

		self.assertTrue(status.dirty)
		self.assertFalse(status.conflicted)

	def test_create_branch_rejects_unsafe_names_and_switches_branch(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		create_branch(repo_root, "lore/example")

		self.assertEqual("lore/example", repository_status(repo_root).branch)
		with self.assertRaises(ValueError):
			create_branch(repo_root, "../unsafe")

	def test_stage_and_commit_only_commits_requested_file(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "lore.json").write_text("lore\n", encoding="utf-8")
		(repo_root / "unrelated.txt").write_text("leave pending\n", encoding="utf-8")

		commit_sha = stage_and_commit(repo_root, ("lore.json",), "Update lore")

		self.assertTrue(commit_sha)
		self.assertEqual(("unrelated.txt",), repository_status(repo_root).changed_files)

	def test_stage_and_commit_leaves_preexisting_staged_unrelated_files_alone(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "lore.json").write_text("lore\n", encoding="utf-8")
		(repo_root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
		run_git(repo_root, "add", "--", "unrelated.txt")

		stage_and_commit(repo_root, ("lore.json",), "Update lore")

		self.assertEqual(("unrelated.txt",), repository_status(repo_root).changed_files)
		self.assertEqual("unrelated\n", (repo_root / "unrelated.txt").read_text(encoding="utf-8"))

	def test_status_reports_clean_repository_with_no_pending_changes(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		status = repository_status(repo_root)

		self.assertEqual("main", status.branch)
		self.assertFalse(status.dirty)
		self.assertEqual((), status.changed_files)
		self.assertFalse(status.conflicted)

	def test_status_raises_for_missing_repository_directory(self) -> None:
		with TemporaryDirectory() as temp_root:
			missing_root = Path(temp_root) / "does-not-exist"
			with self.assertRaises(GitAdapterError):
				repository_status(missing_root)

	def test_status_reports_ahead_behind_and_diverged(self) -> None:
		bare_directory = TemporaryDirectory()
		self.addCleanup(bare_directory.cleanup)
		bare_root = Path(bare_directory.name)
		run_git(bare_root, "init", "--bare", "--initial-branch=main")

		origin_directory = TemporaryDirectory()
		self.addCleanup(origin_directory.cleanup)
		origin_root = Path(origin_directory.name)
		clone_repo(bare_root, origin_root)
		(origin_root / "README.md").write_text("initial\n", encoding="utf-8")
		run_git(origin_root, "add", "--", "README.md")
		run_git(origin_root, "commit", "-m", "Initial")
		run_git(origin_root, "push", "origin", "main")

		clone_a_directory = TemporaryDirectory()
		self.addCleanup(clone_a_directory.cleanup)
		clone_a_root = Path(clone_a_directory.name)
		clone_repo(bare_root, clone_a_root)

		clone_b_directory = TemporaryDirectory()
		self.addCleanup(clone_b_directory.cleanup)
		clone_b_root = Path(clone_b_directory.name)
		clone_repo(bare_root, clone_b_root)

		# clone_a gets a local commit that is not pushed: ahead of upstream.
		(clone_a_root / "local.txt").write_text("local\n", encoding="utf-8")
		run_git(clone_a_root, "add", "--", "local.txt")
		run_git(clone_a_root, "commit", "-m", "Local only")
		ahead_status = repository_status(clone_a_root)
		self.assertEqual(1, ahead_status.ahead)
		self.assertEqual(0, ahead_status.behind)

		# clone_b pushes a commit that clone_a has not fetched: behind (and, once
		# combined with the unpushed local commit above, diverged).
		(clone_b_root / "remote.txt").write_text("remote\n", encoding="utf-8")
		run_git(clone_b_root, "add", "--", "remote.txt")
		run_git(clone_b_root, "commit", "-m", "Remote only")
		run_git(clone_b_root, "push", "origin", "main")
		run_git(clone_a_root, "fetch", "origin")

		diverged_status = repository_status(clone_a_root)
		self.assertEqual(1, diverged_status.ahead)
		self.assertEqual(1, diverged_status.behind)
		self.assertEqual("origin/main", diverged_status.upstream)

	def test_status_reports_merge_conflicts(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "shared.txt").write_text("base\n", encoding="utf-8")
		run_git(repo_root, "add", "--", "shared.txt")
		run_git(repo_root, "commit", "-m", "Add shared file")

		run_git(repo_root, "switch", "--create", "conflicting-branch")
		(repo_root / "shared.txt").write_text("branch change\n", encoding="utf-8")
		run_git(repo_root, "commit", "-am", "Branch change")

		run_git(repo_root, "switch", "main")
		(repo_root / "shared.txt").write_text("main change\n", encoding="utf-8")
		run_git(repo_root, "commit", "-am", "Main change")

		merge_result = run_git_allow_fail(repo_root, "merge", "conflicting-branch")
		self.assertNotEqual(0, merge_result.returncode)

		status = repository_status(repo_root)
		self.assertTrue(status.conflicted)
		self.assertIn("shared.txt", status.conflict_files)

	def test_create_branch_rejects_leading_dash_and_reflog_syntax(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		with self.assertRaises(ValueError):
			create_branch(repo_root, "-not-a-flag")
		with self.assertRaises(ValueError):
			create_branch(repo_root, "lore@{yesterday}")
		with self.assertRaises(ValueError):
			create_branch(repo_root, "lore//example")

	def test_stage_and_commit_rejects_absolute_and_escaping_paths(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		with self.assertRaises(ValueError):
			stage_and_commit(repo_root, (str(repo_root / "lore.json"),), "Update lore")
		with self.assertRaises(ValueError):
			stage_and_commit(repo_root, ("../outside.json",), "Update lore")

	def test_stage_and_commit_raises_when_requested_paths_have_no_staged_changes(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		with self.assertRaises(ValueError):
			stage_and_commit(repo_root, ("README.md",), "No-op commit")

	def test_open_in_github_desktop_raises_actionable_error_when_launcher_missing(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		with patch("webapp.git_adapter.find_github_desktop_launcher", return_value=None):
			with self.assertRaisesRegex(GitAdapterError, "GitHub Desktop"):
				open_in_github_desktop(repo_root)

	def test_repository_remote_url_returns_configured_origin(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		run_git(repo_root, "remote", "add", "origin", "https://example.invalid/Meridian-Rift.git")

		self.assertEqual("https://example.invalid/Meridian-Rift.git", repository_remote_url(repo_root))

	def test_repository_remote_url_returns_none_when_no_remote_configured(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		self.assertIsNone(repository_remote_url(repo_root))

	def test_list_tracked_files_returns_sorted_repo_relative_paths(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		(repo_root / "nested").mkdir()
		(repo_root / "nested" / "b.txt").write_text("b\n", encoding="utf-8")
		(repo_root / "a.txt").write_text("a\n", encoding="utf-8")
		(repo_root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
		run_git(repo_root, "add", "--", "nested/b.txt", "a.txt")
		run_git(repo_root, "commit", "-m", "Add tracked files")

		self.assertEqual(("README.md", "a.txt", "nested/b.txt"), list_tracked_files(repo_root))

	def test_list_tracked_files_raises_when_not_a_git_repository(self) -> None:
		temporary_directory = TemporaryDirectory()
		self.addCleanup(temporary_directory.cleanup)

		with self.assertRaises(GitAdapterError):
			list_tracked_files(Path(temporary_directory.name))

	def test_truncate_output_bounds_long_text(self) -> None:
		long_text = "x" * 20_000

		truncated = git_adapter._truncate_output(long_text, limit=100)

		self.assertTrue(truncated.startswith("x" * 100))
		self.assertIn("truncated, 19900 more characters", truncated)

	def test_status_caps_changed_file_list_and_reports_truncated_count(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		for index in range(5):
			(repo_root / f"file{index}.txt").write_text("pending\n", encoding="utf-8")

		with patch.object(git_adapter, "MAX_CHANGED_FILES", 3):
			status = repository_status(repo_root)

		self.assertEqual(3, len(status.changed_files))
		self.assertEqual(2, status.truncated_change_count)
		self.assertTrue(status.dirty)

	def test_operations_against_the_same_repository_are_serialized(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)

		active = {"count": 0, "max": 0}
		instrumentation_lock = threading.Lock()
		original_run_git = git_adapter._run_git

		def instrumented_run_git(root, arguments, **kwargs):
			with instrumentation_lock:
				active["count"] += 1
				active["max"] = max(active["max"], active["count"])
			try:
				threading.Event().wait(0.05)
				return original_run_git(root, arguments, **kwargs)
			finally:
				with instrumentation_lock:
					active["count"] -= 1

		with patch.object(git_adapter, "_run_git", side_effect=instrumented_run_git):
			threads = [threading.Thread(target=lambda: repository_status(repo_root)) for _ in range(5)]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=5)

		self.assertEqual(1, active["max"])

	def test_operations_against_different_repositories_are_not_serialized(self) -> None:
		temporary_directory_a, repo_root_a = self.make_repo()
		self.addCleanup(temporary_directory_a.cleanup)
		temporary_directory_b, repo_root_b = self.make_repo()
		self.addCleanup(temporary_directory_b.cleanup)

		active = {"count": 0, "max": 0}
		instrumentation_lock = threading.Lock()
		original_run_git = git_adapter._run_git

		def instrumented_run_git(root, arguments, **kwargs):
			with instrumentation_lock:
				active["count"] += 1
				active["max"] = max(active["max"], active["count"])
			try:
				threading.Event().wait(0.2)
				return original_run_git(root, arguments, **kwargs)
			finally:
				with instrumentation_lock:
					active["count"] -= 1

		with patch.object(git_adapter, "_run_git", side_effect=instrumented_run_git):
			threads = [
				threading.Thread(target=lambda: repository_status(repo_root_a)),
				threading.Thread(target=lambda: repository_status(repo_root_b)),
			]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=5)

		self.assertEqual(2, active["max"])

	def test_open_in_github_desktop_uses_detected_launcher(self) -> None:
		temporary_directory, repo_root = self.make_repo()
		self.addCleanup(temporary_directory.cleanup)
		with patch("webapp.git_adapter.find_github_desktop_launcher", return_value="github.bat"), patch(
			"webapp.git_adapter.subprocess.Popen",
		) as popen:
			open_in_github_desktop(repo_root)

		popen.assert_called_once()
		self.assertEqual(["cmd.exe", "/d", "/c", "github.bat", str(repo_root.resolve())], popen.call_args.args[0])


if __name__ == "__main__":
	unittest.main()
