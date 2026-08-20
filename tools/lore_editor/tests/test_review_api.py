from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.lore_editor import api
from tools.lore_editor.api import (
	groups_response,
	list_review_response,
	save_group_response,
	save_review_response,
)


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ReviewApiTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repo_root = Path(self.temp_dir.name)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{
					"type_path": "/datum/language/common",
					"label": "Common",
					"field_profile": "named_datum",
					"base_values": {"name": "Common", "description": "Used by Nanotrasen crews."},
				},
				{
					"type_path": "/obj/item/radio",
					"label": "Radio",
					"field_profile": "atom_like",
					"base_values": {"name": "Radio", "description": "A standard radio."},
				},
			],
		)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/entities/items.json",
			[{
				"id": "items.radio",
				"type_path": "/obj/item/radio",
				"name": "Override radio",
			}],
		)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/groups.json",
			{
				"groups": [
					{
						"id": "languages",
						"label": "Languages",
						"color": "#60a5fa",
						"type_path_prefixes": ["/datum/language"],
					},
					{
						"id": "nanotrasen",
						"label": "Nanotrasen",
						"color": "#34d399",
						"keywords": ["nanotrasen"],
					},
				],
				"assignments": {},
			},
		)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/reviews.json",
			{
				"reviews": {
					"/datum/language/common": {
						"status": "reviewed",
						"reviewed_by": "Zoe",
						"reviewed_at": "2026-08-20T12:00:00+00:00",
						"notes": "Base language is acceptable.",
					},
				},
			},
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_review_items_join_override_review_and_groups(self) -> None:
		response = list_review_response(self.repo_root)
		by_type = {entry["type_path"]: entry for entry in response["entries"]}
		self.assertEqual(by_type["/datum/language/common"]["status"], "reviewed")
		self.assertEqual(by_type["/datum/language/common"]["groups"], ["languages", "nanotrasen"])
		self.assertEqual(
			by_type["/datum/language/common"]["group_match_reasons"]["nanotrasen"],
			["keyword 'nanotrasen' in description"],
		)
		self.assertEqual(by_type["/obj/item/radio"]["status"], "overridden")
		self.assertTrue(by_type["/obj/item/radio"]["has_override"])
		self.assertEqual(response["status_counts"]["reviewed"], 1)
		self.assertEqual(response["status_counts"]["overridden"], 1)

	def test_review_filters_and_sort_are_deterministic(self) -> None:
		filtered = list_review_response(self.repo_root, query="nanotrasen", groups=("languages",), statuses=("reviewed",), sort="type_path")
		self.assertEqual([entry["type_path"] for entry in filtered["entries"]], ["/datum/language/common"])
		sorted_by_status = list_review_response(self.repo_root, sort="status")
		self.assertEqual([entry["status"] for entry in sorted_by_status["entries"]], ["reviewed", "overridden"])

	def test_group_and_review_write_responses_update_the_feed(self) -> None:
		created = save_group_response(self.repo_root, {
			"id": "frontier-cults",
			"label": "Frontier Cults",
			"color": "#f59e0b",
			"keywords": ["cult"],
			"type_path_prefixes": [],
			"assignments": ["/obj/item/radio"],
		})
		self.assertEqual(created["group"]["id"], "frontier-cults")
		reviewed = save_review_response(self.repo_root, "/obj/item/radio", {
			"status": "reviewed",
			"reviewed_by": "Mara",
			"notes": "Radio is acceptable as-is.",
		})
		self.assertEqual(reviewed["review"]["status"], "reviewed")
		response = list_review_response(self.repo_root, groups=("frontier-cults",), statuses=("overridden",))
		self.assertEqual([entry["type_path"] for entry in response["entries"]], ["/obj/item/radio"])

	def test_needs_attention_is_a_writer_action(self) -> None:
		flagged = save_review_response(self.repo_root, "/obj/item/radio", {
			"status": "needs-attention",
			"reviewed_by": "Mara",
			"notes": "Confirm whether this is still Nanotrasen-owned.",
		})
		self.assertEqual(flagged["review"]["status"], "needs-attention")
		response = list_review_response(self.repo_root, statuses=("needs-attention",))
		self.assertEqual([entry["type_path"] for entry in response["entries"]], ["/obj/item/radio"])

	def test_catalog_suppression_requires_explicit_toggles_and_preserves_icon_metadata(self) -> None:
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{
					"type_path": "/obj/item/radio",
					"label": "Radio",
					"field_profile": "atom_like",
					"base_values": {"name": "Radio", "description": "A standard radio."},
					"icon_metadata": {"icon": {"file": "icons/obj/radio.dmi", "state": "radio", "available_states": ["radio"]}},
				},
				{
					"type_path": "/obj/item/radio/directional/east",
					"label": "Radio",
					"field_profile": "atom_like",
					"parent_type": "/obj/item/radio",
					"editable_root": "/obj/item/radio",
					"base_values": {"name": "Radio", "description": "A standard radio."},
					"icon_metadata": {},
				},
				{
					"type_path": "/obj/item/radio/redundant",
					"label": "Radio",
					"field_profile": "atom_like",
					"parent_type": "/obj/item/radio",
					"editable_root": "/obj/item/radio",
					"base_values": {"name": "Radio", "description": "A standard radio."},
					"icon_metadata": {},
				},
			],
		)
		visible = list_review_response(self.repo_root)
		self.assertEqual([entry["type_path"] for entry in visible["entries"]], ["/obj/item/radio"])
		included = list_review_response(self.repo_root, include_directional=True, include_redundant=True)
		by_type = {entry["type_path"]: entry for entry in included["entries"]}
		self.assertEqual(by_type["/obj/item/radio"]["icon_metadata"]["icon"]["state"], "radio")
		self.assertTrue(by_type["/obj/item/radio/directional/east"]["directional"])
		self.assertTrue(by_type["/obj/item/radio/redundant"]["redundant"])

	def test_unknown_filter_values_are_rejected(self) -> None:
		with self.assertRaises(ValueError):
			list_review_response(self.repo_root, sort="newest-first")

	def test_repeated_queries_reuse_the_cached_review_snapshot(self) -> None:
		list_review_response(self.repo_root)
		with patch.object(api, "_build_review_entries_snapshot", wraps=api._build_review_entries_snapshot) as build_spy:
			list_review_response(self.repo_root, query="nanotrasen")
			list_review_response(self.repo_root, sort="status")
			list_review_response(self.repo_root, statuses=("reviewed",))
			build_spy.assert_not_called()

		save_review_response(self.repo_root, "/obj/item/radio", {
			"status": "reviewed",
			"reviewed_by": "Mara",
			"notes": "Confirmed.",
		})
		with patch.object(api, "_build_review_entries_snapshot", wraps=api._build_review_entries_snapshot) as build_spy:
			response = list_review_response(self.repo_root)
			build_spy.assert_called_once()
			by_type = {entry["type_path"]: entry for entry in response["entries"]}
			self.assertEqual(by_type["/obj/item/radio"]["review"]["status"], "reviewed")

	def test_groups_response_includes_counts(self) -> None:
		response = groups_response(self.repo_root)
		self.assertEqual([group["id"] for group in response["groups"]], ["languages", "nanotrasen"])
		self.assertEqual(response["counts"]["languages"], 1)


if __name__ == "__main__":
	unittest.main()
