from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ApiReadTests(unittest.TestCase):
	def make_repo(self) -> Path:
		temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		repo_root = Path(temp_dir.name)
		write_json(
			repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{
					"type_path": "/obj/item/radio",
					"label": "Handheld Radio",
					"editable_root": "/obj/item/radio",
					"parent_type": "/obj/item",
					"field_profile": "atom_like",
					"base_values": {"name": "base radio", "description": "Base description."},
					"icon_metadata": {},
				},
				{
					"type_path": "/obj/item/megaphone",
					"label": "Megaphone",
					"editable_root": "/obj/item/megaphone",
					"parent_type": "/obj/item",
					"field_profile": "atom_like",
					"base_values": {"name": "base megaphone", "description": "Base hailer."},
					"icon_metadata": {},
				},
			],
		)
		write_json(
			repo_root / "config/aphelion/lore_overhaul/entities/jobs.json",
			[
				{"id": "jobs.megaphone", "type_path": "/obj/item/megaphone", "name": "job hailer"},
			],
		)
		write_json(
			repo_root / "config/aphelion/lore_overhaul/entities/items.json",
		[
				{
					"id": "items.radio",
					"type_path": "/obj/item/radio",
					"name": "lore radio",
					"special_desc_requirement": "none",
					"special_desc": "A radio with a hidden note.",
				},
			],
		)
		return repo_root

	def test_list_catalog_and_entries_are_stable_and_source_relative(self) -> None:
		from tools.lore_editor.api import list_catalog, list_entries

		repo_root = self.make_repo()
		targets = list_catalog(repo_root)
		entries = list_entries(repo_root)

		self.assertEqual([target["type_path"] for target in targets], ["/obj/item/megaphone", "/obj/item/radio"])
		self.assertEqual([entry["id"] for entry in entries], ["jobs.megaphone", "items.radio"])
		self.assertEqual(entries[1]["source_file"], "config/aphelion/lore_overhaul/entities/items.json")
		self.assertEqual(entries[1]["base_name"], "base radio")
		self.assertEqual(entries[1]["special_desc_requirement"], "none")
		self.assertEqual(entries[1]["special_desc"], "A radio with a hidden note.")
		self.assertNotIn(str(repo_root), json.dumps(entries))

	def test_entry_filters_preserve_source_order(self) -> None:
		from tools.lore_editor.api import list_entries

		repo_root = self.make_repo()
		self.assertEqual([entry["id"] for entry in list_entries(repo_root, query="radio")], ["items.radio"])
		self.assertEqual([entry["id"] for entry in list_entries(repo_root, category="jobs")], ["jobs.megaphone"])

	def test_review_response_supports_bounded_pages(self) -> None:
		from tools.lore_editor.api import list_review_response

		repo_root = self.make_repo()
		response = list_review_response(repo_root, limit=1)

		self.assertEqual(len(response["entries"]), 1)
		self.assertEqual(response["matched_entry_count"], 2)
		self.assertEqual(response["returned_entry_count"], 1)
		self.assertTrue(response["has_more"])

	def test_review_catalog_index_is_reused_until_catalog_or_groups_change(self) -> None:
		from unittest.mock import patch

		from tools.lore_editor.api import list_review_response

		repo_root = self.make_repo()
		with patch("tools.lore_editor.api.classify_target_details", wraps=None) as classify:
			list_review_response(repo_root)
			first_call_count = classify.call_count
			list_review_response(repo_root)
			self.assertEqual(classify.call_count, first_call_count)

			groups_path = repo_root / "config/aphelion/lore_overhaul/groups.json"
			groups_path.write_text(
				json.dumps({"groups": [{"id": "items", "label": "Items", "color": "#9614d0", "keywords": [], "type_path_prefixes": ["/obj/item"]}], "assignments": {}}),
				encoding="utf-8",
			)
			list_review_response(repo_root)
			self.assertEqual(classify.call_count, first_call_count + 2)

	def test_malformed_source_is_structured_as_issues(self) -> None:
		from tools.lore_editor.api import list_entries_response

		repo_root = self.make_repo()
		bad_path = repo_root / "config/aphelion/lore_overhaul/entities/items.json"
		bad_path.write_text("{not-json", encoding="utf-8")

		response = list_entries_response(repo_root)

		self.assertEqual(response["entries"], [])
		self.assertEqual(response["issues"][0]["severity"], "error")
		self.assertIn("items.json", response["issues"][0]["path"])
		self.assertNotIn(str(repo_root), json.dumps(response))


if __name__ == "__main__":
	unittest.main()
