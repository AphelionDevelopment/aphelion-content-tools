from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class LoreEditorRoundTripTests(unittest.TestCase):
	def test_serialized_entry_round_trips_without_determinism_drift(self) -> None:
		from tools.lore_editor.api import list_entries, save_entry

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			write_json(
				repo_root / "config/aphelion/lore_overhaul/targets.json",
				[{"type_path": "/obj/item/radio", "label": "Radio", "field_profile": "atom_like"}],
			)
			source_path = repo_root / "config/aphelion/lore_overhaul/entities/items.json"
			write_json(
				source_path,
				[{
					"id": "items.radio",
					"type_path": "/obj/item/radio",
					"name": "Station handset",
					"description": "A durable communications device.",
				}],
			)

			serialized_entry = list_entries(repo_root)[0]
			first = save_entry(
				repo_root,
				entry_id=serialized_entry["id"],
				source_file=serialized_entry["source_file"],
				entry=serialized_entry["raw"],
			)
			generated_path = repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
			first_source_bytes = source_path.read_bytes()
			first_generated_bytes = generated_path.read_bytes()

			second = save_entry(
				repo_root,
				entry_id=serialized_entry["id"],
				source_file=serialized_entry["source_file"],
				entry=first["raw"],
			)

			self.assertEqual(second["raw"], serialized_entry["raw"])
			self.assertEqual(source_path.read_bytes(), first_source_bytes)
			self.assertEqual(generated_path.read_bytes(), first_generated_bytes)


if __name__ == "__main__":
	unittest.main()
