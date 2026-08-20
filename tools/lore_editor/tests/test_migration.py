from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.lore_editor.app.migration import migrate_legacy_corpus
from tools.lore_editor.app.storage import ContentStore


class LegacyMigrationTests(unittest.TestCase):

	def test_migration_splits_entity_arrays_and_preserves_values(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			legacy_root = root / "legacy"
			tool_root = root / "tool"
			entities_root = legacy_root / "config" / "aphelion" / "lore_overhaul" / "entities"
			entities_root.mkdir(parents=True)
			(legacy_root / "config" / "aphelion" / "lore_overhaul").mkdir(exist_ok=True)
			(entities_root / "items.json").write_text(json.dumps([
				{"id": "lore.zeta", "type_path": "/obj/zeta", "name": "Zeta"},
				{"id": "lore.alpha", "type_path": "/obj/alpha", "description": "Alpha"},
			]), encoding="utf-8")
			(legacy_root / "config" / "aphelion" / "lore_overhaul" / "groups.json").write_text(json.dumps({
				"groups": [{"id": "items", "label": "Items", "color": "#fff", "keywords": [], "type_path_prefixes": []}],
				"assignments": {"/obj/alpha": ["items"]},
			}), encoding="utf-8")
			(legacy_root / "config" / "aphelion" / "lore_overhaul" / "reviews.json").write_text(json.dumps({
				"reviews": {"/obj/alpha": {"status": "reviewed", "reviewed_by": "Writer", "reviewed_at": "now", "notes": ""}},
			}), encoding="utf-8")
			(legacy_root / "config" / "aphelion" / "lore_overhaul" / "targets.json").write_text("[]", encoding="utf-8")

			result = migrate_legacy_corpus(legacy_root, tool_root)

			self.assertEqual(2, result.entry_count)
			store = ContentStore(tool_root)
			self.assertEqual(["lore.alpha", "lore.zeta"], [record["id"] for record in store.load_records("overrides")])
			self.assertEqual("reviewed", store.load_records("reviews")[0]["status"])
			self.assertEqual("items", store.load_records("assignments")[0]["group_ids"][0])
			self.assertEqual("/obj/alpha", store.load_records("overrides")[0]["type_path"])
			self.assertTrue((tool_root / "catalog" / "targets.json").is_file())


if __name__ == "__main__":
	unittest.main()
