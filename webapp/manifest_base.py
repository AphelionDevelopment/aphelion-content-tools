from __future__ import annotations

import hashlib
from typing import Mapping


MANIFEST_FORMAT_VERSION = 1


def sha256_bytes(value: bytes) -> str:
	return hashlib.sha256(value).hexdigest()


def required_string(payload: Mapping[str, object], field_name: str) -> str:
	value = payload.get(field_name)
	if not isinstance(value, str) or not value:
		raise ValueError(f"Manifest field '{field_name}' must be a non-empty string.")
	return value


def required_string_list(payload: Mapping[str, object], field_name: str) -> tuple[str, ...]:
	value = payload.get(field_name)
	if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
		raise ValueError(f"Manifest field '{field_name}' must be an array of non-empty strings.")
	return tuple(value)
