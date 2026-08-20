from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from tools.dmi import Dmi
from tools.lore_editor.api import create_entry, list_icon_choices, list_review_response, save_entry, save_review_response


class StandaloneApiTests(unittest.TestCase):

	def setUp(self) -> None:
		self.temp_dir = TemporaryDirectory()
		self.root = Path(self.temp_dir.name)
		(self.root / "tools/lore_editor/catalog").mkdir(parents=True)
		(self.root / "tools/lore_editor/content/overrides").mkdir(parents=True)
		(self.root / "tools/lore_editor/content/groups").mkdir(parents=True)
		(self.root / "tools/lore_editor/content/reviews").mkdir(parents=True)
		(self.root / "tools/lore_editor/content/assignments").mkdir(parents=True)
		(self.root / "tools/lore_editor/catalog/targets.json").write_text(json.dumps([
			{
				"type_path": "/obj/item/radio",
				"label": "radio",
				"editable_root": "/obj/item",
				"parent_type": "/obj/item",
				"field_profile": "atom_like",
				"base_values": {"name": "radio", "description": "radio"},
				"icon_metadata": {},
			},
			{
				"type_path": "/obj/item/megaphone",
				"label": "megaphone",
				"editable_root": "/obj/item",
				"parent_type": "/obj/item",
				"field_profile": "atom_like",
				"base_values": {"name": "megaphone", "description": "megaphone"},
				"icon_metadata": {},
			},
		]), encoding="utf-8")
		(self.root / "tools/lore_editor/content/overrides/lore.radio.json").write_text(json.dumps({
			"id": "lore.radio",
			"type_path": "/obj/item/radio",
			"name": "Radio",
		}), encoding="utf-8")

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_review_save_uses_standalone_review_record(self) -> None:
		save_review_response(self.root, "/obj/item/radio", {
			"status": "reviewed",
			"reviewed_by": "Writer",
			"notes": "Approved",
		})

		self.assertTrue((self.root / "tools/lore_editor/content/reviews/review.obj-item-radio.json").is_file())
		response = list_review_response(self.root)
		by_type = {entry["type_path"]: entry for entry in response["entries"]}
		self.assertEqual("reviewed", by_type["/obj/item/radio"]["review"]["status"])

	def test_entry_save_regenerates_standalone_stage(self) -> None:
		save_entry(
			self.root,
			entry_id="lore.radio",
			source_file="tools/lore_editor/content/overrides/lore.radio.json",
			entry={"id": "lore.radio", "type_path": "/obj/item/radio", "name": "Updated radio"},
		)

		self.assertIn(
			'name = "Updated radio"',
			(self.root / "tools/lore_editor/stages/current/generated_lore_overrides.dm").read_text(encoding="utf-8"),
		)

	def test_create_entry_writes_a_single_standalone_override_record(self) -> None:
		created = create_entry(
			self.root,
			source_file="tools/lore_editor/content/overrides/communications.json",
			entry={
				"id": "lore.communications-radio",
				"type_path": "/obj/item/megaphone",
				"name": "Communications radio",
			},
		)

		self.assertEqual("lore.communications-radio", created["id"])
		self.assertEqual(
			"Communications radio",
			json.loads((self.root / "tools/lore_editor/content/overrides/communications.json").read_text(encoding="utf-8"))["name"],
		)

	def test_icon_choices_read_from_configured_game_checkout(self) -> None:
		game_root = self.root / "game"
		dmi = Dmi(32, 32)
		state = dmi.state("radio")
		state.frame(Image.new("RGBA", (32, 32), (255, 0, 0, 255)))
		icon_path = game_root / "modular_aphelion/modules/lore_overhaul/icons/radio.dmi"
		icon_path.parent.mkdir(parents=True)
		dmi.to_file(icon_path)

		choices = list_icon_choices(self.root, asset_root=game_root)

		self.assertEqual("modular_aphelion/modules/lore_overhaul/icons/radio.dmi", choices[0]["file"])


if __name__ == "__main__":
	unittest.main()
