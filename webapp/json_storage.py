from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


RECORD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def canonical_json_bytes(value: object) -> bytes:
	return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def stable_record_filename(record_id: str) -> str:
	if not isinstance(record_id, str) or not RECORD_ID_PATTERN.fullmatch(record_id):
		raise ValueError("Record IDs must contain only letters, numbers, dots, underscores, and hyphens.")
	return f"{record_id}.json"


def atomic_write(path: Path, content: bytes) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(mode="wb", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as temporary_file:
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
