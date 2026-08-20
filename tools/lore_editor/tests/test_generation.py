from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path


GENERATED_DM_PATH = Path(
	"modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
)


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class GenerateDmTests(unittest.TestCase):
	def import_modules(self):
		try:
			generate_module = importlib.import_module("tools.lore_editor.generate")
		except ModuleNotFoundError as exc:
			self.fail(f"tools.lore_editor.generate is missing: {exc}")
		source_module = importlib.import_module("tools.lore_editor.source")
		return generate_module, source_module

	def init_repo(self, repo_root: Path, *, targets: object | None = None) -> Path:
		source_root = repo_root / "config" / "aphelion" / "lore_overhaul"
		entities_root = source_root / "entities"
		entities_root.mkdir(parents=True, exist_ok=True)
		if targets is None:
			targets = [
				{"type_path": "/obj/item/radio"},
				{"type_path": "/obj/item/megaphone"},
			]
		write_json(source_root / "targets.json", targets)
		return entities_root

	def test_generate_dm_orders_entries_omits_unspecified_fields_and_emits_wiki_registry(self) -> None:
		generate_module, source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root)
			write_json(
				entities_root / "beta" / "items.json",
				[
					{
						"id": "beta.radio",
						"type_path": "/obj/item/radio",
						"name": "Beta radio",
					},
				],
			)
			write_json(
				entities_root / "alpha" / "items.json",
				[
					{
						"id": "alpha.zed",
						"type_path": "/obj/item/megaphone",
						"name": "Zed hailer",
					},
					{
						"id": "alpha.able",
						"type_path": "/obj/item/radio",
						"name": "Able radio",
						"description": "Alpha description.",
						"wiki": {
							"enabled": True,
							"slug": "able-radio",
							"summary": "Able summary.",
							"export_icon": False,
						},
					},
				],
			)

			corpus = source_module.load_corpus(repo_root)
			rendered_dm = generate_module.generate_dm(corpus)

			self.assertTrue(rendered_dm.startswith("/// THIS FILE IS GENERATED. DO NOT EDIT BY HAND.\n"))
			self.assertLess(
				rendered_dm.index('/obj/item/radio\n\tname = "Able radio"\n\tdesc = "Alpha description."\n'),
				rendered_dm.index('/obj/item/megaphone\n\tname = "Zed hailer"\n'),
			)
			self.assertLess(
				rendered_dm.index('/obj/item/megaphone\n\tname = "Zed hailer"\n'),
				rendered_dm.index('/obj/item/radio\n\tname = "Beta radio"\n'),
			)
			self.assertIn("/datum/lore_overhaul_entry/alpha_able\n", rendered_dm)
			self.assertEqual(rendered_dm.count("/datum/lore_overhaul_entry/alpha_able"), 2)
			self.assertIn("/datum/autowiki/lore_overhaul/alpha_able\n", rendered_dm)
			self.assertIn('page = "Template:Autowiki/AphelionLore/able-radio"', rendered_dm)
			self.assertIn("entry_type = /datum/lore_overhaul_entry/alpha_able", rendered_dm)
			self.assertNotIn("/datum/autowiki/lore_overhaul/alpha_zed", rendered_dm)
			self.assertIn('\ttarget_type = /obj/item/radio\n', rendered_dm)
			self.assertNotIn('\ttarget_type = "/obj/item/radio"\n', rendered_dm)
			self.assertNotIn('\tdesc = "Zed hailer"\n', rendered_dm)
			self.assertNotIn('\tdesc = "Beta radio"\n', rendered_dm)
			self.assertNotIn("\twiki_icon_file = ", rendered_dm)
			self.assertNotIn("\twiki_icon_state = ", rendered_dm)

	def test_generate_dm_escapes_quotes_and_backslashes(self) -> None:
		generate_module, source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			write_json(
				entities_root / "alpha" / "items.json",
				[
					{
						"id": "alpha.escape",
						"type_path": "/obj/item/radio",
						"name": 'Quoted "radio" \\\\ handset',
						"description": 'Path C:\\\\radio\\\\"quote"',
						"wiki": {
							"enabled": True,
							"slug": "escape-radio",
							"summary": 'Says "hi" from C:\\\\wiki',
							"export_icon": False,
						},
					},
				],
			)

			corpus = source_module.load_corpus(repo_root)
			rendered_dm = generate_module.generate_dm(corpus)

			self.assertIn('\tname = "Quoted \\"radio\\" \\\\\\\\ handset"\n', rendered_dm)
			self.assertIn('\tdesc = "Path C:\\\\\\\\radio\\\\\\\\\\"quote\\""\n', rendered_dm)
			self.assertIn('\twiki_summary = "Says \\"hi\\" from C:\\\\\\\\wiki"\n', rendered_dm)

	def test_generate_dm_emits_special_description_overrides(self) -> None:
		generate_module, source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			write_json(
				entities_root / "fixture" / "items.json",
				{
					"id": "fixture.radio",
					"type_path": "/obj/item/radio",
					"special_desc_requirement": "syndicate",
					"special_desc": "A covert communications device.",
				},
			)

			rendered_dm = generate_module.generate_dm(source_module.load_corpus(repo_root))

		self.assertIn(
			"/obj/item/radio\n\tspecial_desc_requirement = EXAMINE_CHECK_SYNDICATE\n\tspecial_desc = \"A covert communications device.\"",
			rendered_dm,
		)

	def test_generate_dm_emits_catalog_base_values_for_autowiki_fallbacks(self) -> None:
		generate_module, source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(
				repo_root,
				targets=[
					{
						"type_path": "/obj/item/radio",
						"base_values": {"name": "Base radio", "description": "Base radio description."},
					}
				],
			)
			write_json(
				entities_root / "fixture" / "items.json",
				[
					{
						"id": "fixture.base-values",
						"type_path": "/obj/item/radio",
						"wiki": {
							"enabled": True,
							"slug": "fixture-base-values",
							"summary": "Uses catalog fallbacks.",
							"export_icon": False,
						},
					}
				],
			)

			rendered_dm = generate_module.generate_dm(source_module.load_corpus(repo_root))

		self.assertIn('\tbase_name = "Base radio"\n', rendered_dm)
		self.assertIn('\tbase_description = "Base radio description."\n', rendered_dm)

	def test_generate_dm_emits_supported_icon_overrides(self) -> None:
		generate_module, source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			write_json(
				entities_root / "fixture" / "items.json",
				{
					"id": "fixture.icons",
					"type_path": "/obj/item/radio",
					"icons": {
						"icon": {"file": "modular_aphelion/modules/lore_overhaul/icons/radio.dmi", "state": "radio"},
						"worn_icon": {"file": "modular_aphelion/modules/lore_overhaul/icons/radio.dmi", "state": "radio-worn"},
						"inhand_icon": {"file": "modular_aphelion/modules/lore_overhaul/icons/radio.dmi", "state": "radio-hand"},
					},
				},
			)

			rendered_dm = generate_module.generate_dm(source_module.load_corpus(repo_root))

			self.assertIn("\ticon = 'modular_aphelion/modules/lore_overhaul/icons/radio.dmi'\n", rendered_dm)
			self.assertIn('\ticon_state = "radio"\n', rendered_dm)
			self.assertIn("\tworn_icon = 'modular_aphelion/modules/lore_overhaul/icons/radio.dmi'\n", rendered_dm)
			self.assertIn('\tworn_icon_state = "radio-worn"\n', rendered_dm)
			self.assertIn("\tlefthand_file = 'modular_aphelion/modules/lore_overhaul/icons/radio.dmi'\n", rendered_dm)
			self.assertIn("\trighthand_file = 'modular_aphelion/modules/lore_overhaul/icons/radio.dmi'\n", rendered_dm)
			self.assertIn('\tinhand_icon_state = "radio-hand"\n', rendered_dm)

	def test_write_generated_dm_writes_artifact_and_check_only_detects_drift_without_rewriting(self) -> None:
		generate_module, _source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			write_json(
				entities_root / "fixture" / "items.json",
				[
					{
						"id": "fixture.handheld_radio",
						"type_path": "/obj/item/radio",
						"name": "fixture communications handset",
						"description": "A fixture used to test lore generation.",
						"wiki": {
							"enabled": True,
							"slug": "fixture-handheld-radio",
							"summary": "A fixture wiki entry.",
							"export_icon": False,
						},
					},
				],
			)

			generate_module.write_generated_dm(repo_root)

			generated_path = repo_root / GENERATED_DM_PATH
			expected_text = (
				"/// THIS FILE IS GENERATED. DO NOT EDIT BY HAND.\n"
				"/// Source: config/aphelion/lore_overhaul\n\n"
				"/obj/item/radio\n"
				'\tname = "fixture communications handset"\n'
				'\tdesc = "A fixture used to test lore generation."\n\n'
				"/datum/lore_overhaul_entry/fixture_handheld_radio\n"
				'\tentry_id = "fixture.handheld_radio"\n'
				"\ttarget_type = /obj/item/radio\n"
				"\twiki_enabled = TRUE\n"
				'\twiki_slug = "fixture-handheld-radio"\n'
				'\twiki_summary = "A fixture wiki entry."\n'
				"\twiki_export_icon = FALSE\n"
				"\tdisplay_name = \"fixture communications handset\"\n"
				"\tdisplay_description = \"A fixture used to test lore generation.\"\n"
				"\ttype_label = \"/obj/item/radio\"\n\n"
				"/datum/autowiki/lore_overhaul/fixture_handheld_radio\n"
				'\tpage = "Template:Autowiki/AphelionLore/fixture-handheld-radio"\n'
				"\tentry_type = /datum/lore_overhaul_entry/fixture_handheld_radio\n"
			)
			self.assertEqual(generated_path.read_text(encoding="utf-8"), expected_text)

			original_bytes = generated_path.read_bytes()
			generated_path.write_text("drifted artifact\n", encoding="utf-8")

			with self.assertRaisesRegex(ValueError, "generated_lore_overrides\\.dm"):
				generate_module.write_generated_dm(repo_root, check_only=True)

			self.assertEqual(generated_path.read_text(encoding="utf-8"), "drifted artifact\n")

			generate_module.write_generated_dm(repo_root)
			self.assertEqual(generated_path.read_bytes(), original_bytes)

	def test_write_generated_dm_surfaces_validation_diagnostics(self) -> None:
		generate_module, _source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			write_json(
				entities_root / "fixture" / "items.json",
				[
					{
						"id": "fixture.invalid",
						"type_path": "/obj/item/megaphone",
						"name": "fixture invalid target",
					},
				],
			)

			with self.assertRaisesRegex(
				ValueError,
				r"config/aphelion/lore_overhaul/entities/fixture/items\.json#fixture\.invalid\.type_path",
			):
				generate_module.write_generated_dm(repo_root)

	def test_write_generated_dm_rejects_colliding_registry_subtype_names(self) -> None:
		generate_module, _source_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(
				repo_root,
				targets=[
					{"type_path": "/obj/item/radio"},
					{"type_path": "/obj/item/megaphone"},
				],
			)
			write_json(
				entities_root / "alpha" / "items.json",
				[
					{
						"id": "alpha.beta",
						"type_path": "/obj/item/radio",
						"name": "Alpha beta radio",
						"wiki": {
							"enabled": True,
							"slug": "alpha-beta-radio",
							"summary": "Alpha beta summary.",
							"export_icon": False,
						},
					},
				],
			)
			write_json(
				entities_root / "beta" / "items.json",
				[
					{
						"id": "alpha-beta",
						"type_path": "/obj/item/megaphone",
						"name": "Alpha dash beta radio",
						"wiki": {
							"enabled": True,
							"slug": "alpha-dash-beta-radio",
							"summary": "Alpha dash beta summary.",
							"export_icon": False,
						},
					},
				],
			)

			with self.assertRaisesRegex(ValueError, r"/datum/lore_overhaul_entry/alpha_beta"):
				generate_module.write_generated_dm(repo_root)

			with self.assertRaises(ValueError) as exc:
				generate_module.write_generated_dm(repo_root)

			error_text = str(exc.exception)
			self.assertIn(
				"config/aphelion/lore_overhaul/entities/alpha/items.json#alpha.beta",
				error_text,
			)
			self.assertIn(
				"config/aphelion/lore_overhaul/entities/beta/items.json#alpha-beta",
				error_text,
			)


if __name__ == "__main__":
	unittest.main()
