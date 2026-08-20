from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


CONTENT_KINDS = frozenset(("overrides", "groups", "reviews", "assignments"))
RECORD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def canonical_json_bytes(value: object) -> bytes:
	return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def stable_record_filename(record_id: str) -> str:
	if not isinstance(record_id, str) or not RECORD_ID_PATTERN.fullmatch(record_id):
		raise ValueError("Record IDs must contain only letters, numbers, dots, underscores, and hyphens.")
	return f"{record_id}.json"


def _atomic_write(path: Path, content: bytes) -> None:
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


class ContentStore:
	def __init__(self, tool_root: Path):
		self.tool_root = tool_root.resolve()

	def _kind_root(self, kind: str) -> Path:
		if kind not in CONTENT_KINDS:
			raise ValueError(f"Unsupported content kind '{kind}'.")
		return self.tool_root / "content" / kind

	def save_record(self, kind: str, record: object) -> Path:
		if not isinstance(record, dict) or not isinstance(record.get("id"), str):
			raise ValueError("Content records must contain a string id.")
		path = self._kind_root(kind) / stable_record_filename(record["id"])
		_atomic_write(path, canonical_json_bytes(record))
		return path

	def load_records(self, kind: str) -> list[dict[str, object]]:
		kind_root = self._kind_root(kind)
		if not kind_root.exists():
			return []
		records: list[dict[str, object]] = []
		for path in sorted(kind_root.glob("*.json"), key=lambda candidate: candidate.name):
			raw_record = json.loads(path.read_text(encoding="utf-8"))
			if not isinstance(raw_record, dict) or not isinstance(raw_record.get("id"), str):
				raise ValueError(f"{path.as_posix()}: content record must contain a string id.")
			if stable_record_filename(raw_record["id"]) != path.name:
				raise ValueError(f"{path.as_posix()}: filename does not match record id.")
			records.append(raw_record)
		return records
