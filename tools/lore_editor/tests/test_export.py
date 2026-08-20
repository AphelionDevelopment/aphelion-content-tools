from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest
from unittest.mock import patch

from tools.lore_editor import export
from tools.lore_editor.export import apply_export, prepare_export


def run_git(repo_root: Path, *arguments: str) -> None:
	subprocess.run(["git", "-C", str(repo_root), *arguments], check=True, capture_output=True, text=True)


class ExportTests(unittest.TestCase):

	def make_git_repo(self, path: Path) -> None:
		path.mkdir(parents=True)
		run_git(path, "init", "--initial-branch=main")
		run_git(path, "config", "user.name", "Lore Writer")
		run_git(path, "config", "user.email", "writer@example.invalid")

	def make_prepared_pair(self, root: Path, *, with_module: bool = True) -> tuple[Path, Path, Path]:
		tool_root = root / "tool"
		game_root = root / "game"
		stage_root = root / "stages"
		self.make_git_repo(tool_root)
		self.make_git_repo(game_root)
		(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
		(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
		(tool_root / "tools/lore_editor/catalog/targets.json").write_text("[]", encoding="utf-8")
		(game_root / "tgstation.dme").write_text("", encoding="utf-8")
		if with_module:
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
			artifact.parent.mkdir(parents=True)
			artifact.write_text("old\n", encoding="utf-8")
		run_git(tool_root, "add", "--all")
		run_git(tool_root, "commit", "-m", "Tool source")
		run_git(game_root, "add", "--all")
		run_git(game_root, "commit", "-m", "Game source")
		return tool_root, game_root, stage_root

	def test_prepare_export_is_read_only_for_game_checkout_and_apply_is_atomic(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			stage_root = root / "stages"
			self.make_git_repo(tool_root)
			self.make_git_repo(game_root)
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text(json.dumps([{
				"type_path": "/obj/item/radio",
				"label": "radio",
				"editable_root": "/obj/item",
				"parent_type": "/obj/item",
				"field_profile": "atom_like",
				"base_values": {"name": "radio", "description": "radio"},
				"icon_metadata": {},
			}]), encoding="utf-8")
			(tool_root / "tools/lore_editor/content/overrides/lore.radio.json").write_text(json.dumps({
				"id": "lore.radio",
				"type_path": "/obj/item/radio",
				"name": "Updated radio",
			}), encoding="utf-8")
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
			artifact.parent.mkdir(parents=True)
			artifact.write_text("old artifact\n", encoding="utf-8")
			run_git(tool_root, "add", "--all")
			run_git(tool_root, "commit", "-m", "Tool source")
			run_git(game_root, "add", "--all")
			run_git(game_root, "commit", "-m", "Game source")
			before = artifact.read_bytes()

			prepared = prepare_export(tool_root, game_root, stage_root)

			self.assertEqual(before, artifact.read_bytes())
			self.assertTrue((prepared.directory / "manifest.json").is_file())
			self.assertTrue(prepared.artifact_path.is_file())

			apply_export(prepared.directory, game_root)

			self.assertNotEqual(before, artifact.read_bytes())
			self.assertIn('name = "Updated radio"', artifact.read_text(encoding="utf-8"))

	def test_apply_export_refuses_when_game_artifact_changed(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			self.make_git_repo(tool_root)
			self.make_git_repo(game_root)
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text("[]", encoding="utf-8")
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
			artifact.parent.mkdir(parents=True)
			artifact.write_text("old\n", encoding="utf-8")
			run_git(tool_root, "add", "--all")
			run_git(tool_root, "commit", "-m", "Tool source")
			run_git(game_root, "add", "--all")
			run_git(game_root, "commit", "-m", "Game source")

			prepared = prepare_export(tool_root, game_root, root / "stages")
			artifact.write_text("unexpected change\n", encoding="utf-8")

			with self.assertRaises(ValueError):
				apply_export(prepared.directory, game_root)
			self.assertEqual("unexpected change\n", artifact.read_text(encoding="utf-8"))

	def test_apply_export_refuses_when_game_revision_changed(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root, game_root, stage_root = self.make_prepared_pair(root)
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"

			prepared = prepare_export(tool_root, game_root, stage_root)

			(game_root / "unrelated.txt").write_text("new commit\n", encoding="utf-8")
			run_git(game_root, "add", "--all")
			run_git(game_root, "commit", "-m", "Unrelated game change")
			before = artifact.read_bytes()

			with self.assertRaisesRegex(ValueError, "revision changed"):
				apply_export(prepared.directory, game_root)
			self.assertEqual(before, artifact.read_bytes())

	def test_apply_export_refuses_when_game_checkout_is_dirty(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root, game_root, stage_root = self.make_prepared_pair(root)
			artifact = game_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"

			prepared = prepare_export(tool_root, game_root, stage_root)

			(game_root / "uncommitted.txt").write_text("pending\n", encoding="utf-8")
			before = artifact.read_bytes()

			with self.assertRaisesRegex(ValueError, "uncommitted changes"):
				apply_export(prepared.directory, game_root)
			self.assertEqual(before, artifact.read_bytes())

	def test_apply_export_refuses_when_game_module_is_missing(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root, game_root, stage_root = self.make_prepared_pair(root, with_module=False)

			prepared = prepare_export(tool_root, game_root, stage_root)

			with self.assertRaisesRegex(ValueError, "module is missing"):
				apply_export(prepared.directory, game_root)

	def test_prepare_export_removes_partial_stage_directory_on_failure(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root, game_root, stage_root = self.make_prepared_pair(root)

			original_atomic_write = export._atomic_write
			calls = {"count": 0}

			def flaky_atomic_write(path: Path, content: bytes) -> None:
				calls["count"] += 1
				if calls["count"] == 2:
					raise OSError("simulated disk failure")
				original_atomic_write(path, content)

			with patch.object(export, "_atomic_write", side_effect=flaky_atomic_write):
				with self.assertRaises(OSError):
					prepare_export(tool_root, game_root, stage_root)

			self.assertEqual([], list(stage_root.glob("*")) if stage_root.is_dir() else [])

	def test_prepare_export_rejects_game_repository_missing_marker_file(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			self.make_git_repo(tool_root)
			self.make_git_repo(game_root)
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text("[]", encoding="utf-8")
			run_git(tool_root, "add", "--all")
			run_git(tool_root, "commit", "-m", "Tool source")

			with self.assertRaisesRegex(ValueError, "does not look like a Meridian-Rift checkout"):
				prepare_export(tool_root, game_root, root / "stages")

	def test_apply_export_rejects_game_repository_missing_marker_file(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root, game_root, stage_root = self.make_prepared_pair(root)
			prepared = prepare_export(tool_root, game_root, stage_root)
			(game_root / "tgstation.dme").unlink()

			with self.assertRaisesRegex(ValueError, "does not look like a Meridian-Rift checkout"):
				apply_export(prepared.directory, game_root)


if __name__ == "__main__":
	unittest.main()
