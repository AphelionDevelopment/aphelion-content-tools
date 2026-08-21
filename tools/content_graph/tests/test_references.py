from __future__ import annotations

import unittest

from tools.content_graph.references import find_text_references


class FindTextReferencesTests(unittest.TestCase):
	def test_finds_a_reference_when_the_target_fragment_appears_in_the_source_text(self) -> None:
		texts = {
			"modular_nova/modules/a": "// See modular_nova/modules/b for the counterpart.",
			"modular_nova/modules/b": "/obj/item/b\n",
		}
		ids = {
			"modular_nova/modules/a": "module:nova:a",
			"modular_nova/modules/b": "module:nova:b",
		}

		edges = find_text_references(texts, ids)

		self.assertEqual((("module:nova:a", "module:nova:b"),), edges)

	def test_excludes_self_references(self) -> None:
		texts = {"modular_nova/modules/a": "modular_nova/modules/a is self-contained"}
		ids = {"modular_nova/modules/a": "module:nova:a"}

		self.assertEqual((), find_text_references(texts, ids))

	def test_skips_a_source_fragment_with_no_known_id(self) -> None:
		texts = {"unregistered/path": "modular_nova/modules/b"}
		ids = {"modular_nova/modules/b": "module:nova:b"}

		self.assertEqual((), find_text_references(texts, ids))

	def test_skips_empty_text(self) -> None:
		texts = {"modular_nova/modules/a": ""}
		ids = {"modular_nova/modules/a": "module:nova:a", "modular_nova/modules/b": "module:nova:b"}

		self.assertEqual((), find_text_references(texts, ids))

	def test_finds_multiple_references_from_one_source(self) -> None:
		texts = {
			"modular_nova/modules/a": "modular_nova/modules/b and modular_nova/modules/c both apply.",
			"modular_nova/modules/b": "",
			"modular_nova/modules/c": "",
		}
		ids = {
			"modular_nova/modules/a": "module:nova:a",
			"modular_nova/modules/b": "module:nova:b",
			"modular_nova/modules/c": "module:nova:c",
		}

		edges = find_text_references(texts, ids)

		self.assertEqual(
			{("module:nova:a", "module:nova:b"), ("module:nova:a", "module:nova:c")},
			set(edges),
		)


if __name__ == "__main__":
	unittest.main()
