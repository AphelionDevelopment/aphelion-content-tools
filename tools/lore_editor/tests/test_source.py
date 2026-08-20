from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class LoadCorpusTests(unittest.TestCase):
	def import_source_module(self):
		try:
			return importlib.import_module("tools.lore_editor.source")
		except ModuleNotFoundError as exc:
			self.fail(f"tools.lore_editor.source is missing: {exc}")

	def make_repo(self) -> tempfile.TemporaryDirectory[str]:
		return tempfile.TemporaryDirectory()

	def init_repo(self, repo_root: Path, *, targets: object) -> Path:
		source_root = repo_root / "config" / "aphelion" / "lore_overhaul"
		entities_root = source_root / "entities"
		entities_root.mkdir(parents=True, exist_ok=True)
		write_json(source_root / "targets.json", targets)
		return entities_root

	def test_load_corpus_orders_entries_by_relative_source_path(self) -> None:
		source_module = self.import_source_module()
		with self.make_repo() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[])
			write_json(
				entities_root / "zeta" / "second.json",
				[
					{"id": "zeta.second", "type_path": "/obj/item/b"},
				],
			)
			write_json(
				entities_root / "alpha" / "first.json",
				[
					{"id": "alpha.first", "type_path": "/obj/item/a"},
					{"id": "alpha.third", "type_path": "/obj/item/c"},
				],
			)

			corpus = source_module.load_corpus(repo_root)

			self.assertEqual(
				[entry.entry_id for entry in corpus.entries],
				["alpha.first", "alpha.third", "zeta.second"],
			)
			self.assertEqual(
				[str(entry.source_path).replace("\\", "/") for entry in corpus.entries],
				[
					"config/aphelion/lore_overhaul/entities/alpha/first.json",
					"config/aphelion/lore_overhaul/entities/alpha/first.json",
					"config/aphelion/lore_overhaul/entities/zeta/second.json",
				],
			)

	def test_load_corpus_includes_source_path_in_malformed_json_error(self) -> None:
		source_module = self.import_source_module()
		with self.make_repo() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[])
			bad_path = entities_root / "alpha" / "broken.json"
			bad_path.parent.mkdir(parents=True, exist_ok=True)
			bad_path.write_text("{not valid json", encoding="utf-8")

			with self.assertRaisesRegex(
				ValueError,
				r"config/aphelion/lore_overhaul/entities/alpha/broken\.json",
			):
				source_module.load_corpus(repo_root)

	def test_load_corpus_keeps_target_catalog_for_empty_entities_directory(self) -> None:
		source_module = self.import_source_module()
		with self.make_repo() as temp_dir:
			repo_root = Path(temp_dir)
			self.init_repo(
				repo_root,
				targets=[
					{
						"type_path": "/obj/item/radio",
						"fields": ["name", "description"],
					}
				],
			)

			corpus = source_module.load_corpus(repo_root)

			self.assertEqual(corpus.entries, ())
			self.assertEqual(len(corpus.targets), 1)
			self.assertEqual(corpus.targets[0].type_path, "/obj/item/radio")

	def test_load_corpus_parses_optional_special_description_overrides(self) -> None:
		source_module = self.import_source_module()
		with self.make_repo() as temp_dir:
			repo_root = Path(temp_dir)
			entities_root = self.init_repo(repo_root, targets=[])
			write_json(
				entities_root / "items.json",
				{
					"id": "items.radio",
					"type_path": "/obj/item/radio",
					"special_desc_requirement": "syndicate",
					"special_desc": "A covert communications device.",
				},
			)

			entry = source_module.load_corpus(repo_root).entries[0]

			self.assertEqual(entry.special_desc_requirement, "syndicate")
			self.assertEqual(entry.special_desc, "A covert communications device.")


if __name__ == "__main__":
	unittest.main()
