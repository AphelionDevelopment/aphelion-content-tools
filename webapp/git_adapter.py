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


def find_line_in_tracked_files(repo_root: Path, pattern: str, *, glob: str | None = None) -> list[dict[str, object]]:
	"""Return every (path, line, text) match for an extended-regex `pattern` via `git grep`.

	Anchoring/escaping is the caller's responsibility -- this is a thin, generic wrapper. Used for
	best-effort source lookups where no dedicated index exists (e.g. locating a DM type's definition
	line by exact type-path text), so an empty result is a normal "not found," not an error.
	"""
	arguments = ["grep", "-n", "-E", pattern]
	if glob:
		arguments += ["--", glob]
	with _repo_lock(repo_root):
		result = _run_git(repo_root, arguments, allow_nonzero=True)
	if result.returncode not in (0, 1):
		message = result.stderr.strip() or result.stdout.strip() or "git grep failed"
		raise GitAdapterError(_truncate_output(message))
	matches: list[dict[str, object]] = []
	for line in result.stdout.splitlines():
		path, sep1, rest = line.partition(":")
		if not sep1:
			continue
		line_number_text, sep2, text = rest.partition(":")
		if not sep2:
			continue
		try:
			line_number = int(line_number_text)
		except ValueError:
			continue
		matches.append({"path": path, "line": line_number, "text": text})
	return matches


def list_tracked_files(repo_root: Path) -> tuple[str, ...]:
	"""Return every Git-tracked file path in the repository, repo-relative and posix-styled, sorted."""
	with _repo_lock(repo_root):
		result = _run_git(repo_root, ["ls-files", "-z"])
	paths = [path for path in result.stdout.split("\0") if path]
	return tuple(sorted(paths))


def _check_branch_name(branch_name: str) -> None:
	if not branch_name or branch_name.startswith("-") or ".." in branch_name or "//" in branch_name or "@{" in branch_name:
		raise ValueError("Branch name contains unsafe Git reference syntax.")


def create_branch(repo_root: Path, branch_name: str) -> None:
	_check_branch_name(branch_name)
	with _repo_lock(repo_root):
		_run_git(repo_root, ["check-ref-format", "--branch", branch_name])
		_run_git(repo_root, ["switch", "--create", branch_name])


def list_branches(repo_root: Path) -> tuple[str, ...]:
	"""Return every local branch name, sorted."""
	with _repo_lock(repo_root):
		result = _run_git(repo_root, ["branch", "--format=%(refname:short)"])
	return tuple(sorted(line.strip() for line in result.stdout.splitlines() if line.strip()))


def switch_branch(repo_root: Path, branch_name: str) -> None:
	"""Switch to an existing local branch. Git itself refuses the switch if it would overwrite dirty files."""
	_check_branch_name(branch_name)
	with _repo_lock(repo_root):
		_run_git(repo_root, ["check-ref-format", "--branch", branch_name])
		_run_git(repo_root, ["switch", branch_name])


def _resolve_tracked_path(repo_root: Path, relative_path: str) -> Path:
	"""Validate a repository-relative path and return its resolved absolute form.

	Rejects absolute paths and anything that would resolve outside repo_root, the same guard
	stage_and_commit has always applied -- shared here so every new path-taking adapter call gets it.
	"""
	path = Path(relative_path)
	if path.is_absolute():
		raise ValueError("Path must be repository-relative.")
	resolved_root = repo_root.resolve()
	resolved_path = (resolved_root / path).resolve()
	if not resolved_path.is_relative_to(resolved_root):
		raise ValueError(f"Path escapes the repository: {relative_path}")
	return resolved_path


def stage_and_commit(repo_root: Path, relative_paths: tuple[str, ...], message: str) -> str:
	if not relative_paths:
		raise ValueError("At least one repository-relative path is required to commit.")
	if not message.strip():
		raise ValueError("Commit message must not be empty.")
	validated_paths: list[str] = []
	for relative_path in relative_paths:
		_resolve_tracked_path(repo_root, relative_path)
		validated_paths.append(Path(relative_path).as_posix())
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


def git_diff(repo_root: Path, relative_path: str) -> str:
	"""Return the working-tree diff (staged + unstaged combined) for a single repository-relative path."""
	_resolve_tracked_path(repo_root, relative_path)
	posix_path = Path(relative_path).as_posix()
	with _repo_lock(repo_root):
		result = _run_git(repo_root, ["diff", "HEAD", "--", posix_path])
	return _truncate_output(result.stdout)


def open_file_in_default_app(repo_root: Path, relative_path: str) -> None:
	"""Open a repository file or directory with whatever the OS has associated with it.

	Content Graph nodes for modules/master_files overrides/directories point at a directory, not a
	single file -- os.startfile happily opens a directory in Explorer too, so this isn't file-only.
	"""
	resolved_path = _resolve_tracked_path(repo_root, relative_path)
	if not resolved_path.exists():
		raise GitAdapterError(f"Path does not exist: {relative_path}")
	try:
		os.startfile(str(resolved_path))  # noqa: S606 -- Windows-only by design, path is repo-root-bounded
	except OSError as exc:
		raise GitAdapterError(f"Could not open '{relative_path}' in the default app: {exc}") from exc


def reveal_file_in_file_explorer(repo_root: Path, relative_path: str) -> None:
	"""Open Windows Explorer, selecting the path if it's a file or opening it directly if it's a directory."""
	resolved_path = _resolve_tracked_path(repo_root, relative_path)
	if not resolved_path.exists():
		raise GitAdapterError(f"Path does not exist: {relative_path}")
	command = ["explorer.exe", str(resolved_path)] if resolved_path.is_dir() else ["explorer.exe", "/select,", str(resolved_path)]
	try:
		subprocess.Popen(
			command,
			stdin=subprocess.DEVNULL,
			stdout=subprocess.DEVNULL,
			stderr=subprocess.DEVNULL,
		)
	except OSError as exc:
		raise GitAdapterError(f"Could not open File Explorer: {exc}") from exc


_GITHUB_REMOTE_PATTERN = re.compile(
	r"^(?:https://github\.com/|git@github\.com:)(?P<owner>[^/]+)/(?P<repo>.+?)(?:\.git)?/?$"
)


def parse_github_remote(remote_url: str) -> tuple[str, str] | None:
	"""Return (owner, repo) if remote_url looks like a GitHub remote (https or ssh form), else None."""
	match = _GITHUB_REMOTE_PATTERN.match(remote_url.strip())
	if match is None:
		return None
	return match.group("owner"), match.group("repo")


def github_blob_url(repo_root: Path, relative_path: str) -> str | None:
	"""Build a github.com blob (file) or tree (directory) URL for a repository-relative path.

	Returns None if the repository has no 'origin' remote, or that remote isn't a GitHub URL. Pins to
	the current revision (not a branch name) so the link never points at code that has since moved on.
	Uses '/tree/' for directories and '/blob/' for files -- GitHub 404s a directory path under '/blob/'.
	"""
	remote_url = repository_remote_url(repo_root)
	if remote_url is None:
		return None
	parsed = parse_github_remote(remote_url)
	if parsed is None:
		return None
	owner, repo = parsed
	revision = repository_revision(repo_root)
	posix_path = Path(relative_path).as_posix()
	resolved_path = (repo_root.resolve() / Path(relative_path))
	segment = "tree" if resolved_path.is_dir() else "blob"
	return f"https://github.com/{owner}/{repo}/{segment}/{revision}/{posix_path}"


_PR_SUBJECT_PATTERN = re.compile(r"\(#(\d+)\)\s*$")
_LOG_L_FORMAT = "\x02%H\x1f%an\x1f%ad\x1f%s\x03"


def line_history(repo_root: Path, relative_path: str, line_number: int, *, max_commits: int = 5) -> list[dict[str, object]]:
	"""Return up to max_commits commits that touched relative_path's given line, newest first.

	Uses `git log -L` -- Git's own line-history tool -- so this needs no new dependency and stays
	accurate across the line's history. Each entry includes a best-effort GitHub pull request URL
	parsed from a trailing "(#1234)" in the commit subject (the standard squash-merge convention);
	commits with no such marker simply have pr_url=None. No GitHub API calls are made.
	"""
	if line_number < 1:
		raise ValueError("line_number must be a positive integer.")
	posix_path = Path(relative_path).as_posix()
	with _repo_lock(repo_root):
		result = _run_git(
			repo_root,
			[
				"log",
				f"-L{line_number},{line_number}:{posix_path}",
				f"-n{max_commits}",
				"--no-color",
				"--date=short",
				f"--format={_LOG_L_FORMAT}",
			],
		)
	remote_url = repository_remote_url(repo_root)
	github_repo = parse_github_remote(remote_url) if remote_url else None

	commits: list[dict[str, object]] = []
	for chunk in result.stdout.split("\x02")[1:]:
		header, _, rest = chunk.partition("\x03")
		commit_hash, author, date, subject = header.split("\x1f", 3)
		pr_url = None
		if github_repo is not None:
			pr_match = _PR_SUBJECT_PATTERN.search(subject)
			if pr_match is not None:
				pr_url = f"https://github.com/{github_repo[0]}/{github_repo[1]}/pull/{pr_match.group(1)}"
		commits.append({
			"commit": commit_hash,
			"short_commit": commit_hash[:12],
			"author": author,
			"date": date,
			"subject": subject,
			"diff": rest.strip("\n"),
			"pr_url": pr_url,
		})
	return commits
