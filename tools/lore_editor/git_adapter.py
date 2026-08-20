from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
from threading import Lock


class GitAdapterError(ValueError):
	pass


@dataclass(frozen=True)
class RepositoryStatus:
	branch: str
	upstream: str | None
	ahead: int
	behind: int
	dirty: bool
	changed_files: tuple[str, ...]
	conflict_files: tuple[str, ...]
	truncated_change_count: int = 0

	@property
	def conflicted(self) -> bool:
		return bool(self.conflict_files)


CONFLICT_STATUS_CODES = frozenset(("DD", "AU", "UD", "UA", "DU", "AA", "UU"))

MAX_GIT_OUTPUT_CHARACTERS = 8_000
MAX_CHANGED_FILES = 2_000

_REPO_LOCKS: dict[Path, Lock] = {}
_REPO_LOCKS_REGISTRY_LOCK = Lock()


def _repo_lock(repo_root: Path) -> Lock:
	"""Return a lock shared by every caller operating on this repository path.

	Two concurrent multi-step operations (e.g. stage_and_commit's add+commit) against the
	same repository could otherwise interleave their Git index changes.
	"""
	resolved_root = repo_root.resolve()
	with _REPO_LOCKS_REGISTRY_LOCK:
		lock = _REPO_LOCKS.get(resolved_root)
		if lock is None:
			lock = Lock()
			_REPO_LOCKS[resolved_root] = lock
		return lock


def _truncate_output(text: str, *, limit: int = MAX_GIT_OUTPUT_CHARACTERS) -> str:
	if len(text) <= limit:
		return text
	return text[:limit] + f"\n... (truncated, {len(text) - limit} more characters)"


def find_git_executable() -> str:
	local_app_data = os.environ.get("LOCALAPPDATA")
	if local_app_data:
		github_desktop_root = Path(local_app_data) / "GitHubDesktop"
		candidates = sorted(
			github_desktop_root.glob("app-*/resources/app/git/cmd/git.exe"),
			key=lambda path: path.as_posix(),
			reverse=True,
		)
		if candidates:
			return str(candidates[0])
	path = shutil.which("git")
	if path:
		return path
	raise GitAdapterError("Git was not found. Install GitHub Desktop or configure a Git executable.")


def find_github_desktop_launcher() -> str | None:
	path = shutil.which("github")
	if path:
		return path
	local_app_data = os.environ.get("LOCALAPPDATA")
	if local_app_data:
		for candidate in (
			Path(local_app_data) / "GitHubDesktop/bin/github.bat",
			Path(local_app_data) / "GitHubDesktop/bin/github.exe",
		):
			if candidate.is_file():
				return str(candidate)
	return None


def _run_git(repo_root: Path, arguments: list[str], *, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
	resolved_root = repo_root.resolve()
	if not resolved_root.is_dir():
		raise GitAdapterError(f"Git repository directory does not exist: {repo_root}")
	try:
		result = subprocess.run(
			[find_git_executable(), "-C", str(resolved_root), *arguments],
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
		)
	except OSError as exc:
		raise GitAdapterError(f"Git could not be started: {exc}") from exc
	if result.returncode != 0 and not allow_nonzero:
		message = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
		raise GitAdapterError(_truncate_output(message))
	return result


def repository_status(repo_root: Path) -> RepositoryStatus:
	with _repo_lock(repo_root):
		status_result = _run_git(repo_root, ["status", "--porcelain=v1", "-b"])
	lines = status_result.stdout.splitlines()
	if not lines or not lines[0].startswith("## "):
		raise GitAdapterError("Git did not return a branch status.")
	branch_summary = lines[0][3:]
	branch = branch_summary.split("...", 1)[0]
	if branch == "HEAD":
		branch = "(detached HEAD)"
	upstream = None
	ahead = 0
	behind = 0
	if "..." in branch_summary:
		upstream_summary = branch_summary.split("...", 1)[1]
		upstream = upstream_summary.split(" [", 1)[0]
		match = re.search(r"\[([^]]+)\]", upstream_summary)
		if match:
			for detail in match.group(1).split(", "):
				if detail.startswith("ahead "):
					ahead = int(detail[6:])
				elif detail.startswith("behind "):
					behind = int(detail[7:])
	changed_files: list[str] = []
	conflict_files: list[str] = []
	total_change_count = 0
	for line in lines[1:]:
		if len(line) < 4:
			continue
		status_code = line[:2]
		file_name = line[3:]
		if " -> " in file_name:
			file_name = file_name.rsplit(" -> ", 1)[-1]
		total_change_count += 1
		if status_code in CONFLICT_STATUS_CODES:
			conflict_files.append(file_name)
		if len(changed_files) < MAX_CHANGED_FILES:
			changed_files.append(file_name)
	return RepositoryStatus(
		branch=branch,
		upstream=upstream,
		ahead=ahead,
		behind=behind,
		dirty=total_change_count > 0,
		changed_files=tuple(changed_files),
		conflict_files=tuple(conflict_files),
		truncated_change_count=total_change_count - len(changed_files),
	)


def repository_revision(repo_root: Path) -> str:
	with _repo_lock(repo_root):
		return _run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()


def repository_remote_url(repo_root: Path, remote_name: str = "origin") -> str | None:
	"""Return the configured remote URL, or None if unavailable (not a repo, or no such remote)."""
	with _repo_lock(repo_root):
		result = _run_git(repo_root, ["remote", "get-url", remote_name], allow_nonzero=True)
	if result.returncode != 0:
		return None
	url = result.stdout.strip()
	return url or None


def create_branch(repo_root: Path, branch_name: str) -> None:
	if not branch_name or branch_name.startswith("-") or ".." in branch_name or "//" in branch_name or "@{" in branch_name:
		raise ValueError("Branch name contains unsafe Git reference syntax.")
	with _repo_lock(repo_root):
		_run_git(repo_root, ["check-ref-format", "--branch", branch_name])
		_run_git(repo_root, ["switch", "--create", branch_name])


def stage_and_commit(repo_root: Path, relative_paths: tuple[str, ...], message: str) -> str:
	if not relative_paths:
		raise ValueError("At least one repository-relative path is required to commit.")
	if not message.strip():
		raise ValueError("Commit message must not be empty.")
	resolved_root = repo_root.resolve()
	validated_paths: list[str] = []
	for relative_path in relative_paths:
		path = Path(relative_path)
		if path.is_absolute():
			raise ValueError("Commit paths must be repository-relative.")
		resolved_path = (resolved_root / path).resolve()
		if not resolved_path.is_relative_to(resolved_root):
			raise ValueError(f"Commit path escapes the repository: {relative_path}")
		validated_paths.append(path.as_posix())
	with _repo_lock(repo_root):
		_run_git(repo_root, ["add", "--", *validated_paths])
		no_changes = _run_git(repo_root, ["diff", "--cached", "--quiet", "--", *validated_paths], allow_nonzero=True)
		if no_changes.returncode == 0:
			raise ValueError("The requested paths contain no staged changes.")
		_run_git(repo_root, ["commit", "--only", "-m", message, "--", *validated_paths])
		return _run_git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()


def open_in_github_desktop(repo_root: Path) -> None:
	launcher = find_github_desktop_launcher()
	if launcher is None:
		raise GitAdapterError("GitHub Desktop's launcher was not found. Install it or open the repository manually.")
	resolved_root = repo_root.resolve()
	if not resolved_root.is_dir():
		raise GitAdapterError(f"Repository directory does not exist: {repo_root}")
	try:
		command = [launcher, str(resolved_root)]
		if launcher.casefold().endswith(".bat"):
			command = ["cmd.exe", "/d", "/c", launcher, str(resolved_root)]
		subprocess.Popen(
			command,
			cwd=str(resolved_root),
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except OSError as exc:
		raise GitAdapterError(f"GitHub Desktop could not be opened: {exc}") from exc
