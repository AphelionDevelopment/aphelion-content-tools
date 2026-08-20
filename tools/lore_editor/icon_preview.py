from __future__ import annotations

from io import BytesIO
from pathlib import Path

from tools.dmi import Dmi

from .source import resolve_repo_path


class IconPreviewNotFound(ValueError):
	"""Raised when a requested DMI state is absent."""


def _approved_icon_root(repo_root: Path, relative_path: Path) -> Path:
	parts = relative_path.parts
	if parts and parts[0] == "icons":
		return repo_root.resolve() / "icons"
	if parts[:3] == ("modular_nova", "master_files", "icons"):
		return repo_root.resolve() / "modular_nova" / "master_files" / "icons"
	if len(parts) >= 5 and parts[0] in {"modular_aphelion", "modular_nova"} and parts[1] == "modules":
		try:
			icons_index = parts.index("icons", 2, len(parts) - 1)
		except ValueError:
			icons_index = -1
		if icons_index > 2:
			return repo_root.resolve() / Path(*parts[:icons_index + 1])
	raise ValueError("Icon preview only serves files from the repository icons directory, modular module icons directories, or modular_nova master-file icons.")


def _resolve_icon_path(repo_root: Path, relative_file: str) -> Path:
	relative_path = Path(relative_file)
	if relative_path.suffix.casefold() != ".dmi":
		raise ValueError("Icon preview only supports .dmi files.")
	resolved_path = resolve_repo_path(repo_root, relative_path)
	icon_root = _approved_icon_root(repo_root, relative_path)
	if not resolved_path.is_relative_to(icon_root.resolve()):
		raise ValueError("Icon preview path must remain inside its approved icon directory.")
	if not resolved_path.is_file():
		raise ValueError(f"Icon file '{relative_path.as_posix()}' does not exist.")
	return resolved_path


def list_icon_files(repo_root: Path) -> list[str]:
	resolved_root = repo_root.resolve()
	search_roots = [
		resolved_root / "icons",
		resolved_root / "modular_nova" / "master_files" / "icons",
		resolved_root / "modular_aphelion" / "modules",
		resolved_root / "modular_nova" / "modules",
	]
	files: set[str] = set()
	for search_root in search_roots:
		if not search_root.exists():
			continue
		for icon_path in search_root.rglob("*.dmi"):
			relative_path = icon_path.relative_to(resolved_root)
			try:
				_approved_icon_root(resolved_root, relative_path)
			except ValueError:
				continue
			files.add(relative_path.as_posix())
	return sorted(files)


def list_icon_states(repo_root: Path, relative_file: str) -> list[str]:
	icon_path = _resolve_icon_path(repo_root, relative_file)
	try:
		dmi = Dmi.from_file(icon_path)
	except Exception as exc:
		raise ValueError(f"Icon file '{relative_file}' could not be read: {exc}.") from exc
	return sorted(state.name for state in dmi.states if state.name)


def _get_icon_state(dmi: Dmi, requested_state: str):
	try:
		return dmi.get_state(requested_state)
	except KeyError:
		if len(dmi.states) == 1 and not dmi.states[0].name:
			return dmi.states[0]
		raise


def render_icon_preview(repo_root: Path, relative_file: str, state: str) -> bytes:
	icon_path = _resolve_icon_path(repo_root, relative_file)
	try:
		dmi = Dmi.from_file(icon_path)
		icon_state = _get_icon_state(dmi, state)
	except KeyError as exc:
		raise IconPreviewNotFound(f"Icon state '{state}' was not found in {relative_file}.") from exc
	except Exception as exc:
		raise ValueError(f"Icon file '{relative_file}' could not be read: {exc}.") from exc

	if not icon_state.frames:
		raise ValueError(f"Icon state '{state}' has no frames in {relative_file}.")

	output = BytesIO()
	icon_state.frames[0].save(output, format="PNG")
	return output.getvalue()
