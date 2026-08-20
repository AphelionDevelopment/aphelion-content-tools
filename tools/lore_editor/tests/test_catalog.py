from __future__ import annotations

import importlib
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class RefreshCatalogTests(unittest.TestCase):
	def import_modules(self):
		try:
			catalog_module = importlib.import_module("tools.lore_editor.catalog")
		except ModuleNotFoundError as exc:
			self.fail(f"tools.lore_editor.catalog is missing: {exc}")
		source_module = importlib.import_module("tools.lore_editor.source")
		validation_module = importlib.import_module("tools.lore_editor.validation")
		return catalog_module, source_module, validation_module

	def init_repo(self, repo_root: Path, *, targets: object | None = None) -> Path:
		source_root = repo_root / "config" / "aphelion" / "lore_overhaul"
		entities_root = source_root / "entities"
		entities_root.mkdir(parents=True, exist_ok=True)
		if targets is None:
			targets = []
		write_json(source_root / "targets.json", targets)
		return entities_root

	def make_target(
		self,
		*,
		type_path: str,
		label: str,
		editable_root: str,
		parent_type: str,
		field_profile: str,
		name: str,
		description: str | None,
		icon_metadata: object | None = None,
	) -> dict[str, object]:
		target = {
			"type_path": type_path,
			"label": label,
			"editable_root": editable_root,
			"parent_type": parent_type,
			"field_profile": field_profile,
			"base_values": {
				"name": name,
				"description": description,
			},
			"icon_metadata": icon_metadata or {},
		}
		return target

	def test_editable_roots_cover_general_items_and_machinery(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		root_paths = {str(root["type_path"]) for root in catalog_module.EDITABLE_ROOTS}

		self.assertIn("/obj/item", root_paths)
		self.assertIn("/obj/machinery", root_paths)
		self.assertNotIn("/obj/item/radio", root_paths)
		self.assertNotIn("/obj/item/megaphone", root_paths)

	def test_refresh_catalog_orders_targets_and_preserves_base_values(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(repo_root, targets=[{"type_path": "/obj/item/obsolete"}])
			probe_output_path = repo_root / "data" / "lore_overhaul_targets.json"
			write_json(
				probe_output_path,
				[
					self.make_target(
						type_path="/obj/item/radio/headset",
						label="Command Headset",
						editable_root="/obj/item",
						parent_type="/obj/item/radio",
						field_profile="atom_like",
						name="command headset",
						description="A headset assigned to command staff.",
						icon_metadata={
							"icon": {
								"file": "icons/obj/devices/radio.dmi",
								"state": "headset",
								"available_states": ["headset_alt", "headset"],
							},
						},
					),
					self.make_target(
						type_path="/datum/language/common",
						label="Galactic Common",
						editable_root="/datum/language",
						parent_type="/datum/language",
						field_profile="named_datum",
						name="Galactic Common",
						description="The most widespread trade language in the sector.",
					),
					self.make_target(
						type_path="/obj/item/megaphone",
						label="Megaphone",
						editable_root="/obj/item",
						parent_type="/obj/item",
						field_profile="atom_like",
						name="megaphone",
						description="A loud hailer for crowd control.",
						icon_metadata={
							"icon": {
								"file": "icons/obj/devices/radio.dmi",
								"state": "megaphone",
								"available_states": ["megaphone"],
							},
						},
					),
				],
			)

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output_path):
				targets = catalog_module.refresh_catalog(repo_root)

			self.assertEqual(
				[target["type_path"] for target in targets],
				[
					"/datum/language/common",
					"/obj/item/megaphone",
					"/obj/item/radio/headset",
				],
			)
			self.assertEqual(
				targets[0]["base_values"],
				{
					"name": "Galactic Common",
					"description": "The most widespread trade language in the sector.",
				},
			)
			self.assertEqual(
				targets[2]["icon_metadata"]["icon"],
				{"file": "icons/obj/devices/radio.dmi", "state": "headset"},
			)
			written_targets = json.loads(
				(repo_root / "config" / "aphelion" / "lore_overhaul" / "targets.json").read_text(encoding="utf-8")
			)
			self.assertEqual(written_targets, targets)

	def test_standalone_refresh_runs_probe_in_game_repo_and_writes_tool_catalog(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			game_root.mkdir(parents=True)
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			probe_output = game_root / "data/lore_overhaul_targets.json"
			write_json(probe_output, [self.make_target(
				type_path="/obj/item/radio",
				label="Radio",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="radio",
				description="A radio.",
			)])

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output) as probe:
				targets = catalog_module.refresh_catalog(tool_root, game_repo_root=game_root)

			probe.assert_called_once_with(game_root.resolve())
			self.assertEqual(1, len(targets))
			self.assertTrue((tool_root / "tools/lore_editor/catalog/targets.json").is_file())
			manifest = json.loads((tool_root / "tools/lore_editor/catalog/manifest.json").read_text(encoding="utf-8"))
			self.assertEqual(1, manifest["target_count"])
			self.assertEqual(manifest["snapshot_sha256"], __import__("hashlib").sha256(
				(tool_root / "tools/lore_editor/catalog/targets.json").read_bytes()
			).hexdigest())

	def test_refresh_catalog_rejects_game_repository_missing_marker_file(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			game_root.mkdir(parents=True)

			with self.assertRaisesRegex(ValueError, "does not look like a Meridian-Rift checkout"):
				catalog_module.refresh_catalog(tool_root, game_repo_root=game_root)

	def test_refresh_catalog_rejects_game_repository_with_mismatched_remote(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			tool_root = root / "tool"
			game_root = root / "game"
			(tool_root / "tools/lore_editor/catalog").mkdir(parents=True)
			game_root.mkdir(parents=True)
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			subprocess.run(["git", "-C", str(game_root), "init", "--initial-branch=main"], check=True, capture_output=True, text=True)
			subprocess.run(
				["git", "-C", str(game_root), "remote", "add", "origin", "https://example.invalid/some-other-fork.git"],
				check=True, capture_output=True, text=True,
			)

			with self.assertRaisesRegex(ValueError, "does not look like Meridian-Rift"):
				catalog_module.refresh_catalog(tool_root, game_repo_root=game_root)

	def test_refresh_catalog_rejects_targets_outside_configured_roots(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			targets_path = repo_root / "config" / "aphelion" / "lore_overhaul" / "targets.json"
			original_text = targets_path.read_text(encoding="utf-8")
			probe_output_path = repo_root / "data" / "lore_overhaul_targets.json"
			write_json(
				probe_output_path,
				[
					self.make_target(
						type_path="/obj/item/flashlight",
						label="Flashlight",
						editable_root="/obj/item/radio",
						parent_type="/obj/item",
						field_profile="atom_like",
						name="flashlight",
						description="A handheld light source.",
					),
				],
			)

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output_path):
				with self.assertRaisesRegex(ValueError, "/obj/item/flashlight"):
					catalog_module.refresh_catalog(repo_root)

			self.assertEqual(targets_path.read_text(encoding="utf-8"), original_text)

	def test_refresh_catalog_accepts_species_targets(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(repo_root)
			probe_output_path = repo_root / "data" / "lore_overhaul_targets.json"
			write_json(
				probe_output_path,
				[
					self.make_target(
						type_path="/datum/species/human",
						label="Human",
						editable_root="/datum/species",
						parent_type="/datum/species",
						field_profile="named_datum",
						name="Human",
						description="Humans are the dominant species in the known galaxy.",
					),
				],
			)

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output_path):
				targets = catalog_module.refresh_catalog(repo_root)

			self.assertEqual(targets[0]["type_path"], "/datum/species/human")
			self.assertEqual(targets[0]["editable_root"], "/datum/species")

	def test_refresh_catalog_rejects_malformed_probe_json_without_replacing_targets(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])
			targets_path = repo_root / "config" / "aphelion" / "lore_overhaul" / "targets.json"
			original_text = targets_path.read_text(encoding="utf-8")
			probe_output_path = repo_root / "data" / "lore_overhaul_targets.json"
			probe_output_path.parent.mkdir(parents=True, exist_ok=True)
			probe_output_path.write_text("{not valid json", encoding="utf-8")

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output_path):
				with self.assertRaisesRegex(ValueError, "malformed JSON"):
					catalog_module.refresh_catalog(repo_root)

			self.assertEqual(targets_path.read_text(encoding="utf-8"), original_text)

	def test_normalize_targets_accepts_empty_byond_icon_metadata_list(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()

		target = self.make_target(
			type_path="/datum/language/common",
			label="Galactic Common",
			editable_root="/datum/language",
			parent_type="/datum/language",
			field_profile="named_datum",
			name="Galactic Common",
			description="The common galactic tongue.",
			icon_metadata=[],
		)
		target["icon_metadata"] = []

		normalized = catalog_module.normalize_targets([target])

		self.assertEqual(normalized[0]["icon_metadata"], {})

	def test_normalize_targets_drops_redundant_icon_state_lists(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		target = self.make_target(
			type_path="/obj/item/radio",
			label="Radio",
			editable_root="/obj/item",
			parent_type="/obj/item",
			field_profile="atom_like",
			name="Radio",
			description="A standard radio.",
			icon_metadata={
				"icon": {
					"file": "icons/obj/radio.dmi",
					"state": "radio",
					"available_states": ["radio", "radio_alt"],
				},
			},
		)

		normalized = catalog_module.normalize_targets([target])

		self.assertEqual(normalized[0]["icon_metadata"], {
			"icon": {
				"file": "icons/obj/radio.dmi",
				"state": "radio",
			},
		})

	def test_validate_corpus_rejects_entries_absent_from_refreshed_catalog(self) -> None:
		catalog_module, source_module, validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root)
			probe_output_path = repo_root / "data" / "lore_overhaul_targets.json"
			write_json(
				probe_output_path,
				[
					self.make_target(
						type_path="/obj/item/radio",
						label="Handheld Radio",
						editable_root="/obj/item",
						parent_type="/obj/item",
						field_profile="atom_like",
						name="handheld radio",
						description="A station-issued communications device.",
					),
				],
			)
			write_json(
				entities_root / "fixture" / "items.json",
				[
					{
						"id": "fixture.invalid_target",
						"type_path": "/obj/item/megaphone",
						"name": "fixture invalid target",
					},
				],
			)

			with patch.object(catalog_module, "_run_catalog_probe", return_value=probe_output_path):
				catalog_module.refresh_catalog(repo_root)

			corpus = source_module.load_corpus(repo_root)
			issues = validation_module.validate_corpus(repo_root, corpus)

			self.assertEqual(
				[(issue.path, issue.message, issue.severity) for issue in issues],
				[
					(
						"config/aphelion/lore_overhaul/entities/fixture/items.json#fixture.invalid_target.type_path",
						"Type path '/obj/item/megaphone' is not present in config/aphelion/lore_overhaul/targets.json.",
						"error",
					)
				],
			)

	def test_run_catalog_probe_rejects_stale_compiled_dmb(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			compiled_dmb_path = repo_root / "tgstation.dmb"
			compiled_dmb_path.write_bytes(b"stale artifact")
			stale_time_ns = time.time_ns() - 5_000_000_000
			os.utime(compiled_dmb_path, ns=(stale_time_ns, stale_time_ns))

			with patch.object(catalog_module, "_run_external_command"):
				with self.assertRaisesRegex(ValueError, "did not produce a fresh"):
					catalog_module._run_catalog_probe(repo_root)

	def test_external_command_can_accept_probe_shutdown_code(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		process = unittest.mock.Mock()
		process.stdout = ["probe complete\n"]
		process.wait.return_value = 8256

		with patch.object(catalog_module.subprocess, "Popen", return_value=process):
			return_code = catalog_module._run_external_command(
				Path("."),
				["DreamDaemon.exe"],
				"Lore catalog probe runtime",
				allow_nonzero_exit=True,
			)

		self.assertEqual(return_code, 8256)

	def test_compute_catalog_drift_reports_removed_changed_and_stale_entries(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		old_targets = [
			self.make_target(
				type_path="/obj/item/radio",
				label="Radio",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="radio",
				description="A standard radio.",
			),
			self.make_target(
				type_path="/obj/item/flashlight",
				label="Flashlight",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="flashlight",
				description="A flashlight.",
			),
			self.make_target(
				type_path="/obj/item/wrench",
				label="Wrench",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="wrench",
				description="A wrench.",
			),
		]
		new_targets = [
			self.make_target(
				type_path="/obj/item/radio",
				label="Radio",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="radio",
				description="An updated radio.",
			),
			self.make_target(
				type_path="/obj/item/wrench",
				label="Wrench",
				editable_root="/obj/item",
				parent_type="/obj/item",
				field_profile="atom_like",
				name="wrench",
				description="A wrench.",
			),
		]

		drift = catalog_module.compute_catalog_drift(
			old_targets, new_targets, frozenset({"/obj/item/radio", "/obj/item/wrench"}),
		)

		self.assertEqual(("/obj/item/flashlight",), drift.removed_type_paths)
		self.assertEqual(("/obj/item/radio",), drift.changed_type_paths)
		self.assertEqual(("/obj/item/radio",), drift.stale_entry_type_paths)
		self.assertTrue(drift.has_drift)

	def test_compute_catalog_drift_reports_no_drift_for_identical_snapshots(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		targets = [self.make_target(
			type_path="/obj/item/radio",
			label="Radio",
			editable_root="/obj/item",
			parent_type="/obj/item",
			field_profile="atom_like",
			name="radio",
			description="A standard radio.",
		)]

		drift = catalog_module.compute_catalog_drift(targets, targets, frozenset({"/obj/item/radio"}))

		self.assertEqual((), drift.removed_type_paths)
		self.assertEqual((), drift.changed_type_paths)
		self.assertEqual((), drift.stale_entry_type_paths)
		self.assertFalse(drift.has_drift)

	def test_read_current_targets_returns_empty_list_when_missing(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)

			self.assertEqual([], catalog_module.read_current_targets(repo_root))

	def test_read_current_targets_reads_the_committed_snapshot(self) -> None:
		catalog_module, _source_module, _validation_module = self.import_modules()
		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(repo_root, targets=[{"type_path": "/obj/item/radio"}])

			targets = catalog_module.read_current_targets(repo_root)

			self.assertEqual([{"type_path": "/obj/item/radio"}], targets)


if __name__ == "__main__":
	unittest.main()
