from __future__ import annotations

import os
from pathlib import Path
import tempfile

from webapp.git_adapter import repository_status
from webapp.path_safety import resolve_repo_path
from .markers import render_marker_line


_LINE_ENDINGS = ("\r\n", "\n", "\r")


def _split_line_ending(line: str) -> tuple[str, str]:
	for ending in _LINE_ENDINGS:
		if line.endswith(ending):
			return line[: -len(ending)], ending
	return line, ""


def _atomic_write(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode="wb",
		delete=False,
		dir=path.parent,
		prefix=f".{path.name}.",
		suffix=".tmp",
	) as temporary_file:
		temporary_file.write(content)
		temporary_file.flush()
		os.fsync(temporary_file.fileno())
	temporary_path = Path(temporary_file.name)
	try:
		os.replace(temporary_path, path)
	except Exception:
		if temporary_path.exists():
			temporary_path.unlink()
		raise


def apply_marker_label_edit(
	game_repo_root: Path,
	core_file: str,
	line_number: int,
	expected_line: str,
	new_label: str,
) -> None:
	"""Rewrite a single marker's label in place, refusing if the line has changed since it was loaded.

	Optimistic concurrency, not a staged prepare/apply flow: this only ever patches one line of an
	existing file (no artifact is generated), so the safety requirement is simpler -- the caller
	supplies `expected_line` (the marker line exactly as it read it, e.g. from the last scan), and this
	refuses to write unless the file's current content at `line_number` still matches byte-for-byte.
	"""
	if line_number < 1:
		raise ValueError("line_number must be a positive integer.")
	if not new_label.strip():
		raise ValueError("New label must not be empty.")
	resolved_root = game_repo_root.resolve()
	status = repository_status(resolved_root)
	if status.conflicted:
		raise ValueError("The game checkout has unresolved Git conflicts; resolve them before editing markers.")

	file_path = resolve_repo_path(resolved_root, Path(core_file))
	if not file_path.is_file():
		raise ValueError(f"Core file does not exist: {core_file}")

	text = file_path.read_text(encoding="utf-8")
	lines = text.splitlines(keepends=True)
	if line_number > len(lines):
		raise ValueError(f"Line {line_number} is out of range for {core_file}.")

	index = line_number - 1
	current_content, line_ending = _split_line_ending(lines[index])
	if current_content != expected_line:
		raise ValueError(
			f"{core_file}:{line_number} changed since this marker was loaded; rescan and try again."
		)

	lines[index] = render_marker_line(current_content, new_label) + line_ending
	_atomic_write(file_path, "".join(lines).encode("utf-8"))
