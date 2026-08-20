from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.lore_editor.workspace import WorkspaceLayout


class WorkspaceLayoutTests(unittest.TestCase):

	def test_standalone_layout_uses_tool_owned_content_and_stage_paths(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			(root / "tools/lore_editor/catalog").mkdir(parents=True)

			layout = WorkspaceLayout.from_root(root)

			self.assertTrue(layout.standalone)
			self.assertEqual(Path("tools/lore_editor/catalog/targets.json"), layout.targets_path)
			self.assertEqual(Path("tools/lore_editor/content/overrides"), layout.entities_root)
			self.assertEqual(
				Path("tools/lore_editor/stages/current/generated_lore_overrides.dm"),
				layout.generated_dm_path,
			)

	def test_legacy_layout_remains_available_for_game_repo_compatibility(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			layout = WorkspaceLayout.from_root(Path(temporary_directory))

			self.assertFalse(layout.standalone)
			self.assertEqual(Path("config/aphelion/lore_overhaul/targets.json"), layout.targets_path)
			self.assertEqual(Path("config/aphelion/lore_overhaul/entities"), layout.entities_root)
			self.assertEqual(
				Path("modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"),
				layout.generated_dm_path,
			)


if __name__ == "__main__":
	unittest.main()
