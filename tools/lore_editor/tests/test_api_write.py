from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ApiWriteTests(unittest.TestCase):
	def make_repo(self) -> tuple[Path, Path]:
		temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		repo_root = Path(temp_dir.name)
		write_json(
			repo_root / "config/aphelion/lore_overhaul/targets.json",
			[{
				"type_path": "/obj/item/radio",
				"label": "Radio",
				"field_profile": "atom_like",
			}],
		)
		source_path = repo_root / "config/aphelion/lore_overhaul/entities/items.json"
		write_json(
			source_path,
			[{
				"id": "items.radio",
				"type_path": "/obj/item/radio",
				"name": "Old radio",
			}],
		)
		return repo_root, source_path

	def test_save_entry_validates_writes_atomically_and_generates_dm(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, source_path = self.make_repo()
		result = save_entry(
			repo_root,
			entry_id="items.radio",
			source_file="config/aphelion/lore_overhaul/entities/items.json",
			entry={
				"id": "items.radio",
				"type_path": "/obj/item/radio",
				"name": "New radio",
				"description": "A rewritten handset.",
			},
		)

		self.assertEqual(result["id"], "items.radio")
		self.assertEqual(json.loads(source_path.read_text(encoding="utf-8"))[0]["name"], "New radio")
		self.assertIn('name = "New radio"', (repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm").read_text(encoding="utf-8"))

	def test_save_entry_persists_special_description_overrides(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, source_path = self.make_repo()
		result = save_entry(
			repo_root,
			entry_id="items.radio",
			source_file="config/aphelion/lore_overhaul/entities/items.json",
			entry={
				"id": "items.radio",
				"type_path": "/obj/item/radio",
				"special_desc_requirement": "syndicate",
				"special_desc": "A covert communications device.",
			},
		)

		self.assertEqual(result["special_desc_requirement"], "syndicate")
		self.assertEqual(result["special_desc"], "A covert communications device.")
		serialized = json.loads(source_path.read_text(encoding="utf-8"))[0]
		self.assertEqual(serialized["special_desc_requirement"], "syndicate")
		self.assertEqual(serialized["special_desc"], "A covert communications device.")
		generated = (repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm").read_text(encoding="utf-8")
		self.assertIn("special_desc_requirement = EXAMINE_CHECK_SYNDICATE", generated)
		self.assertIn('special_desc = "A covert communications device."', generated)

	def test_save_entry_rejects_invalid_candidate_without_modifying_source_or_generated(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, source_path = self.make_repo()
		original_source = source_path.read_bytes()
		generated_path = repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
		generated_path.parent.mkdir(parents=True, exist_ok=True)
		generated_path.write_bytes(b"original generated\n")

		with self.assertRaisesRegex(ValueError, "type_path"):
			save_entry(
				repo_root,
				entry_id="items.radio",
				source_file="config/aphelion/lore_overhaul/entities/items.json",
				entry={
					"id": "items.radio",
					"type_path": "/obj/item/not_in_catalog",
					"name": "Bad radio",
				},
			)

		self.assertEqual(source_path.read_bytes(), original_source)
		self.assertEqual(generated_path.read_bytes(), b"original generated\n")

	def test_save_entry_rejects_source_path_traversal(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, _source_path = self.make_repo()
		with self.assertRaises(ValueError):
			save_entry(
				repo_root,
				entry_id="items.radio",
				source_file="config/aphelion/lore_overhaul/entities/../targets.json",
				entry={"id": "items.radio", "type_path": "/obj/item/radio"},
			)

	def test_save_entry_appends_new_entry_to_a_domain_array(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, source_path = self.make_repo()
		write_json(
			repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{"type_path": "/obj/item/radio", "label": "Radio", "field_profile": "atom_like"},
				{"type_path": "/obj/item/megaphone", "label": "Megaphone", "field_profile": "atom_like"},
			],
		)

		save_entry(
			repo_root,
			entry_id="items.megaphone",
			source_file="config/aphelion/lore_overhaul/entities/items.json",
			entry={
				"id": "items.megaphone",
				"type_path": "/obj/item/megaphone",
				"name": "Station hailer",
			},
		)

		self.assertEqual(len(json.loads(source_path.read_text(encoding="utf-8"))), 2)

	def test_save_entry_rejects_mismatched_source_file(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, _source_path = self.make_repo()
		other_path = repo_root / "config/aphelion/lore_overhaul/entities/jobs.json"
		write_json(other_path, [])
		with self.assertRaisesRegex(ValueError, "different source file"):
			save_entry(
				repo_root,
				entry_id="items.radio",
				source_file="config/aphelion/lore_overhaul/entities/jobs.json",
				entry={"id": "items.radio", "type_path": "/obj/item/radio"},
			)
		self.assertEqual(json.loads(other_path.read_text(encoding="utf-8")), [])

	def test_create_entry_can_create_a_new_override_group_file(self) -> None:
		from tools.lore_editor.api import create_entry, list_entity_files

		repo_root, _source_path = self.make_repo()
		write_json(
			repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{"type_path": "/obj/item/radio", "label": "Radio", "field_profile": "atom_like"},
				{"type_path": "/obj/item/megaphone", "label": "Megaphone", "field_profile": "atom_like"},
			],
		)
		result = create_entry(
			repo_root,
			source_file="config/aphelion/lore_overhaul/entities/languages.json",
			entry={
				"id": "languages.megaphone",
				"type_path": "/obj/item/megaphone",
				"name": "Common megaphone",
			},
		)

		self.assertEqual(result["id"], "languages.megaphone")
		self.assertEqual(
			json.loads((repo_root / "config/aphelion/lore_overhaul/entities/languages.json").read_text(encoding="utf-8"))[0]["name"],
			"Common megaphone",
		)
		self.assertIn("config/aphelion/lore_overhaul/entities/languages.json", list_entity_files(repo_root))

	def test_create_entry_rejects_paths_outside_entity_groups(self) -> None:
		from tools.lore_editor.api import create_entry

		repo_root, _source_path = self.make_repo()
		with self.assertRaises(ValueError):
			create_entry(
				repo_root,
				source_file="config/aphelion/lore_overhaul/entities/../groups.json",
				entry={"id": "bad", "type_path": "/obj/item/radio"},
			)

	def test_generation_failure_restores_source_and_generated_bytes(self) -> None:
		from tools.lore_editor.api import save_entry

		repo_root, source_path = self.make_repo()
		generated_path = repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
		generated_path.parent.mkdir(parents=True, exist_ok=True)
		generated_path.write_bytes(b"original generated\n")
		original_source = source_path.read_bytes()

		with patch("tools.lore_editor.api.write_generated_dm", side_effect=ValueError("generation failed")):
			with self.assertRaisesRegex(ValueError, "generation failed"):
				save_entry(
					repo_root,
					entry_id="items.radio",
					source_file="config/aphelion/lore_overhaul/entities/items.json",
					entry={"id": "items.radio", "type_path": "/obj/item/radio", "name": "New radio"},
				)

		self.assertEqual(source_path.read_bytes(), original_source)
		self.assertEqual(generated_path.read_bytes(), b"original generated\n")


if __name__ == "__main__":
	unittest.main()
