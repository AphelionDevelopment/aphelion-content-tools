from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.lore_editor.generate import write_generated_dm


class StandaloneGenerationTests(unittest.TestCase):

	def test_generation_writes_to_local_stage_instead_of_game_module(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			(root / "tools/lore_editor/catalog").mkdir(parents=True)
			(root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(root / "tools/lore_editor/catalog/targets.json").write_text(json.dumps([
				{
					"type_path": "/obj/item/radio",
					"label": "radio",
					"editable_root": "/obj/item",
					"parent_type": "/obj/item",
					"field_profile": "atom_like",
					"base_values": {"name": "radio", "description": "radio"},
					"icon_metadata": {},
				},
			]), encoding="utf-8")
			(root / "tools/lore_editor/content/overrides/lore.radio.json").write_text(json.dumps({
				"id": "lore.radio",
				"type_path": "/obj/item/radio",
				"name": "Field Radio",
			}), encoding="utf-8")

			write_generated_dm(root)

			self.assertTrue((root / "tools/lore_editor/stages/current/generated_lore_overrides.dm").is_file())
			self.assertFalse((root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm").exists())


if __name__ == "__main__":
	unittest.main()
