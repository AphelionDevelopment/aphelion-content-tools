from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from tools.dmi import Dmi
from webapp.server import create_server


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_dmi(path: Path, state_name: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	dmi = Dmi(32, 32)
	state = dmi.state(state_name)
	state.frame(Image.new("RGBA", (32, 32), (0, 255, 0, 255)))
	dmi.to_file(path)


class ServerApiTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repo_root = Path(self.temp_dir.name)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{
					"type_path": "/obj/item/radio",
					"label": "Radio",
					"field_profile": "atom_like",
				},
				{
					"type_path": "/obj/item/radio/weather_monitor",
					"label": "Weather monitor",
					"field_profile": "atom_like",
					"base_values": {
						"name": "Weather monitor",
						"description": "A monitor for local weather conditions.",
					},
				},
			],
		)
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/entities/items.json",
			[{
				"id": "items.radio",
				"type_path": "/obj/item/radio",
				"name": "Old radio",
			}],
		)
		write_dmi(self.repo_root / "modular_aphelion/modules/lore_overhaul/icons/radio.dmi", "radio")
		write_dmi(self.repo_root / "icons/obj/radio.dmi", "radio")
		write_dmi(self.repo_root / "icons/obj/clothing/head/default.dmi", "")
		write_dmi(self.repo_root / "modular_nova/master_files/icons/obj/clothing/neck.dmi", "cape_admiral")
		self.server = create_server(self.repo_root)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()
		self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

	def tearDown(self) -> None:
		self.server.shutdown()
		self.thread.join(timeout=5)
		self.server.server_close()
		self.temp_dir.cleanup()

	def request(self, path: str, *, method: str = "GET", payload: object | None = None) -> tuple[int, str, object]:
		body = None
		headers = {}
		if payload is not None:
			body = json.dumps(payload).encode("utf-8")
			headers["Content-Type"] = "application/json"
		request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
		try:
			with urllib.request.urlopen(request, timeout=5) as response:
				content_type = response.headers.get_content_type()
				response_body = response.read()
				return response.status, content_type, json.loads(response_body) if content_type == "application/json" else response_body
		except urllib.error.HTTPError as exc:
			content_type = exc.headers.get_content_type()
			response_body = exc.read()
			return exc.code, content_type, json.loads(response_body) if content_type == "application/json" else response_body

	def test_catalog_entries_validation_and_save_endpoints(self) -> None:
		catalog_status, _catalog_type, catalog = self.request("/api/catalog")
		self.assertEqual(catalog_status, 200)
		self.assertEqual(catalog["targets"][0]["type_path"], "/obj/item/radio")

		entries_status, _entries_type, entries = self.request("/api/entries")
		self.assertEqual(entries_status, 200)
		self.assertEqual(entries["entries"][0]["id"], "items.radio")

		candidate = {
			"id": "items.radio",
			"type_path": "/obj/item/not_in_catalog",
			"name": "Rejected radio",
		}
		validate_status, _validate_type, validation = self.request(
			"/api/validate",
			method="POST",
			payload={
				"entries": [candidate],
			},
		)
		self.assertEqual(validate_status, 200)
		self.assertFalse(validation["valid"])

		updated = {**candidate, "type_path": "/obj/item/radio", "name": "New radio"}
		save_status, _save_type, saved = self.request(
			"/api/entries/items.radio",
			method="PUT",
			payload={
				"source_file": "config/aphelion/lore_overhaul/entities/items.json",
				"entry": updated,
			},
		)
		self.assertEqual(save_status, 200)
		self.assertTrue(saved["saved"])
		self.assertEqual(saved["entry"]["id"], "items.radio")
		self.assertEqual(saved["entry"]["name"], "New radio")

		generate_status, _generate_type, generated = self.request("/api/generate", method="POST", payload={})
		self.assertEqual(generate_status, 200)
		self.assertTrue(generated["generated"])

	def test_review_endpoint_includes_catalog_targets_without_overrides(self) -> None:
		status, _content_type, review = self.request("/api/review")
		self.assertEqual(status, 200)
		by_type = {entry["type_path"]: entry for entry in review["entries"]}
		self.assertTrue(by_type["/obj/item/radio"]["approved"])
		self.assertFalse(by_type["/obj/item/radio/weather_monitor"]["approved"])
		self.assertEqual(by_type["/obj/item/radio/weather_monitor"]["base_name"], "Weather monitor")

		search_status, _search_type, search = self.request("/api/review?q=weather")
		self.assertEqual(search_status, 200)
		self.assertEqual([entry["type_path"] for entry in search["entries"]], ["/obj/item/radio/weather_monitor"])

	def test_icon_endpoint_serves_png_and_rejects_unknown_state(self) -> None:
		choices_status, _choices_type, choices = self.request("/api/icons")
		self.assertEqual(choices_status, 200)
		self.assertEqual(choices["icons"][0]["file"], "modular_aphelion/modules/lore_overhaul/icons/radio.dmi")
		self.assertEqual(choices["icons"][0]["states"], ["radio"])

		query = urllib.parse.urlencode({
			"file": "modular_aphelion/modules/lore_overhaul/icons/radio.dmi",
			"state": "radio",
		})
		status, content_type, body = self.request(f"/api/icon?{query}")
		self.assertEqual(status, 200)
		self.assertEqual(content_type, "image/png")
		self.assertTrue(body.startswith(b"\x89PNG"))

		bad_query = urllib.parse.urlencode({
			"file": "modular_aphelion/modules/lore_overhaul/icons/radio.dmi",
			"state": "missing",
		})
		bad_status, _bad_type, _bad_body = self.request(f"/api/icon?{bad_query}")
		self.assertEqual(bad_status, 404)

		core_query = urllib.parse.urlencode({"file": "icons/obj/radio.dmi", "state": "radio"})
		core_status, core_content_type, core_body = self.request(f"/api/icon?{core_query}")
		self.assertEqual(core_status, 200)
		self.assertEqual(core_content_type, "image/png")
		self.assertTrue(core_body.startswith(b"\x89PNG"))

		states_status, _states_type, states = self.request(
			"/api/icon-states?" + urllib.parse.urlencode({"file": "icons/obj/radio.dmi"}),
		)
		self.assertEqual(states_status, 200)
		self.assertEqual(states["states"], ["radio"])

		master_query = urllib.parse.urlencode({
			"file": "modular_nova/master_files/icons/obj/clothing/neck.dmi",
			"state": "cape_admiral",
		})
		master_status, master_content_type, master_body = self.request(f"/api/icon?{master_query}")
		self.assertEqual(master_status, 200)
		self.assertEqual(master_content_type, "image/png")
		self.assertTrue(master_body.startswith(b"\x89PNG"))

		default_query = urllib.parse.urlencode({
			"file": "icons/obj/clothing/head/default.dmi",
			"state": "/obj/item/clothing/head/security_cap/service",
		})
		default_status, default_content_type, default_body = self.request(f"/api/icon?{default_query}")
		self.assertEqual(default_status, 200)
		self.assertEqual(default_content_type, "image/png")
		self.assertTrue(default_body.startswith(b"\x89PNG"))

		master_states_status, _master_states_type, master_states = self.request(
			"/api/icon-states?" + urllib.parse.urlencode({"file": "modular_nova/master_files/icons/obj/clothing/neck.dmi"}),
		)
		self.assertEqual(master_states_status, 200)
		self.assertEqual(master_states["states"], ["cape_admiral"])

		files_status, _files_type, files = self.request("/api/icon-files")
		self.assertEqual(files_status, 200)
		self.assertIn("modular_nova/master_files/icons/obj/clothing/neck.dmi", files["files"])

	def test_group_and_review_routes_persist_writer_decisions(self) -> None:
		group_status, _group_type, group = self.request(
			"/api/groups",
			method="POST",
			payload={
				"id": "company-review",
				"label": "Company review",
				"color": "#34d399",
				"keywords": ["nanotrasen"],
				"type_path_prefixes": [],
			},
		)
		self.assertEqual(group_status, 200)
		self.assertEqual(group["group"]["id"], "company-review")

		review_status, _review_type, review = self.request(
			"/api/reviews/%2Fobj%2Fitem%2Fradio",
			method="PUT",
			payload={
				"status": "reviewed",
				"reviewed_by": "Zoe",
				"notes": "Reviewed from the browser.",
			},
		)
		self.assertEqual(review_status, 200)
		self.assertEqual(review["review"]["status"], "reviewed")

		groups_status, _groups_type, groups = self.request("/api/groups")
		self.assertEqual(groups_status, 200)
		self.assertEqual(groups["groups"][-1]["id"], "company-review")

	def test_group_update_and_needs_attention_routes_persist_writer_decisions(self) -> None:
		group_status, _group_type, group = self.request(
			"/api/groups/languages",
			method="PUT",
			payload={
				"label": "Company review updated",
				"color": "#bb44f0",
				"keywords": ["nanotrasen", "interdyne"],
				"type_path_prefixes": ["/obj/item/radio"],
			},
		)
		self.assertEqual(group_status, 200)
		self.assertEqual(group["group"]["keywords"], ["nanotrasen", "interdyne"])
		attention_status, _attention_type, attention = self.request(
			"/api/reviews/%2Fobj%2Fitem%2Fradio",
			method="PUT",
			payload={
				"status": "needs-attention",
				"reviewed_by": "Zoe",
				"notes": "Needs a lore decision.",
			},
		)
		self.assertEqual(attention_status, 200)
		self.assertEqual(attention["review"]["status"], "needs-attention")

	def test_tool_routes_expose_only_the_allowlist(self) -> None:
		status, _content_type, payload = self.request("/api/tools")
		self.assertEqual(status, 200)
		self.assertEqual(
			{tool["id"] for tool in payload["tools"]},
			{"catalog-refresh", "validate", "generate", "refresh-validate", "scan-content"},
		)
		bad_status, _bad_type, _bad_payload = self.request("/api/tools/arbitrary-command", method="POST")
		self.assertEqual(bad_status, 400)

	def test_create_entry_route_creates_a_new_entity_group(self) -> None:
		write_json(
			self.repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{"type_path": "/obj/item/radio", "label": "Radio", "field_profile": "atom_like"},
				{"type_path": "/obj/item/megaphone", "label": "Megaphone", "field_profile": "atom_like"},
			],
		)
		status, _content_type, response = self.request(
			"/api/entries",
			method="POST",
			payload={
				"source_file": "config/aphelion/lore_overhaul/entities/communications.json",
				"entry": {
					"id": "communications.megaphone",
					"type_path": "/obj/item/megaphone",
					"name": "Communications megaphone",
				},
			},
		)
		self.assertEqual(status, 200)
		self.assertTrue(response["created"])
		self.assertEqual(response["entry"]["id"], "communications.megaphone")


if __name__ == "__main__":
	unittest.main()
