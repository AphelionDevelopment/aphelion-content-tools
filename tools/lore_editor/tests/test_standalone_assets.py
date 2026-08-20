from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from tools.dmi import Dmi
from tools.lore_editor.source import load_corpus
from tools.lore_editor.validation import validate_corpus


class StandaloneAssetValidationTests(unittest.TestCase):

	def test_validation_reads_icon_assets_from_configured_game_checkout(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			(tool_root / "tools/lore_editor/content/overrides").mkdir(parents=True)
			(tool_root / "tools/lore_editor/catalog/targets.json").write_text(json.dumps([
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
			(tool_root / "tools/lore_editor/content/overrides/lore.radio.json").write_text(json.dumps({
				"id": "lore.radio",
				"type_path": "/obj/item/radio",
				"icons": {"icon": {"file": "icons/radio.dmi", "state": "radio"}},
			}), encoding="utf-8")
			dmi = Dmi(32, 32)
			state = dmi.state("radio")
			state.frame(Image.new("RGBA", (32, 32), (255, 0, 0, 255)))
			dmi_path = game_root / "icons/radio.dmi"
			dmi_path.parent.mkdir(parents=True)
			dmi.to_file(dmi_path)

			corpus = load_corpus(tool_root)

			self.assertEqual([], validate_corpus(tool_root, corpus, asset_root=game_root))


if __name__ == "__main__":
	unittest.main()
