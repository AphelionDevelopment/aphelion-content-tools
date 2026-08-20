from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.lore_editor.app.manifest import CatalogManifest, ExportManifest, sha256_bytes
from tools.lore_editor.app.storage import ContentStore, canonical_json_bytes, stable_record_filename


class ContentStoreTests(unittest.TestCase):

	def test_records_are_stored_individually_and_loaded_in_stable_order(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			store = ContentStore(Path(temporary_directory))
			store.save_record("overrides", {"id": "lore.zeta", "type_path": "/obj/zeta"})
			store.save_record("overrides", {"id": "lore.alpha", "type_path": "/obj/alpha"})

			self.assertEqual(
				["lore.alpha", "lore.zeta"],
				[record["id"] for record in store.load_records("overrides")],
			)
			self.assertTrue((Path(temporary_directory) / "content" / "overrides" / "lore.alpha.json").is_file())
			self.assertFalse((Path(temporary_directory) / "content" / "overrides" / "records.json").exists())

	def test_canonical_json_is_independent_of_mapping_order(self) -> None:
		first = {"type_path": "/obj/example", "id": "lore.example"}
		second = {"id": "lore.example", "type_path": "/obj/example"}

		self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
		self.assertEqual(
			b'{\n  "id": "lore.example",\n  "type_path": "/obj/example"\n}\n',
			canonical_json_bytes(first),
		)

	def test_record_filename_rejects_path_traversal(self) -> None:
		with self.assertRaises(ValueError):
			stable_record_filename("../outside")

	def test_saved_json_is_canonical(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			store = ContentStore(Path(temporary_directory))
			store.save_record("groups", {"keywords": [], "id": "nanotrasen"})
			path = Path(temporary_directory) / "content" / "groups" / "nanotrasen.json"

			self.assertEqual(
				canonical_json_bytes(json.loads(path.read_text(encoding="utf-8"))),
				path.read_bytes(),
			)

	def test_catalog_manifest_round_trips_with_stable_hash(self) -> None:
		manifest = CatalogManifest(
			snapshot_sha256=sha256_bytes(b"catalog"),
			game_repo_revision="abc123",
			generated_at="2026-08-20T12:00:00+00:00",
			target_count=42,
		)

		self.assertEqual(manifest, CatalogManifest.from_dict(manifest.to_dict()))
		self.assertEqual(1, manifest.format_version)

	def test_export_manifest_rejects_failed_validation(self) -> None:
		with self.assertRaises(ValueError):
			ExportManifest.from_dict({
				"format_version": 1,
				"tool_repo_revision": "abc123",
				"tool_branch": "lore/example",
				"catalog_sha256": sha256_bytes(b"catalog"),
				"game_repo_revision": "def456",
				"entry_ids": ["lore.example"],
				"type_paths": ["/obj/example"],
				"generated_artifact_sha256": sha256_bytes(b"dm"),
				"validation": {"valid": False, "issues": [{"path": "x", "message": "bad"}]},
			})

	def test_export_manifest_rejects_invalid_optional_base_hash(self) -> None:
		with self.assertRaises(ValueError):
			ExportManifest.from_dict({
				"format_version": 1,
				"tool_repo_revision": "abc123",
				"tool_branch": "lore/example",
				"catalog_sha256": sha256_bytes(b"catalog"),
				"game_repo_revision": "def456",
				"entry_ids": [],
				"type_paths": [],
				"generated_artifact_sha256": sha256_bytes(b"dm"),
				"base_artifact_sha256": 42,
				"validation": {"valid": True, "issues": []},
			})


if __name__ == "__main__":
	unittest.main()
