from __future__ import annotations

import json
from pathlib import Path


def resolve_repo_path(repo_root: Path, relative_path: Path) -> Path:
	if relative_path.is_absolute():
		raise ValueError(f"Absolute repository path is not allowed: {relative_path}")
	resolved_root = repo_root.resolve()
	resolved_path = (resolved_root / relative_path).resolve()
	if not resolved_path.is_relative_to(resolved_root):
		raise ValueError(f"Repository path escapes root: {relative_path}")
	return resolved_path


def read_json_file(repo_root: Path, relative_path: Path) -> object:
	source_path = resolve_repo_path(repo_root, relative_path)
	try:
		return json.loads(source_path.read_text(encoding="utf-8"))
	except json.JSONDecodeError as exc:
		raise ValueError(
			f"{relative_path.as_posix()}: malformed JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
		) from exc
