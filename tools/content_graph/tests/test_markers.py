from __future__ import annotations

import unittest

from tools.content_graph.markers import parse_markers


class MarkerParsingTests(unittest.TestCase):
	def test_addition_block_with_module_id_and_reason(self) -> None:
		text = (
			"// NOVA EDIT ADDITION START - SHUTTLE_TOGGLE - (Optional Reason/comment)\n"
			"var/adminEmergencyNoRecall = FALSE\n"
			"// NOVA EDIT ADDITION END\n"
		)

		edges = parse_markers(text, frozenset({"SHUTTLE_TOGGLE"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("NOVA", edge.owner)
		self.assertEqual("addition", edge.edit_type)
		self.assertEqual(1, edge.line_number)
		self.assertEqual("SHUTTLE_TOGGLE", edge.source_module_id)
		self.assertEqual("exact", edge.attribution)
		self.assertIsNone(edge.original_text)

	def test_removal_block_wrapped_in_block_comment(self) -> None:
		text = (
			"/* // NOVA EDIT REMOVAL START - SHUTTLE_TOGGLE - (Optional Reason/comment)\n"
			"for(var/obj/docking_port/stationary/S in stationary)\n"
			"*/ // NOVA EDIT REMOVAL END\n"
		)

		edges = parse_markers(text, frozenset({"shuttle_toggle"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("removal", edge.edit_type)
		# module ids on disk are lowercase; the marker text is uppercase -- must resolve case-insensitively
		self.assertEqual("shuttle_toggle", edge.source_module_id)
		self.assertEqual("exact", edge.attribution)

	def test_change_marker_captures_original_text_and_has_no_module_id(self) -> None:
		text = "if(SHUTTLE_STRANDED, SHUTTLE_ESCAPE, SHUTTLE_DISABLED) // NOVA EDIT CHANGE - ORIGINAL: if(SHUTTLE_STRANDED, SHUTTLE_ESCAPE)\n"

		edges = parse_markers(text, frozenset({"shuttle_toggle"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("change", edge.edit_type)
		self.assertEqual("if(SHUTTLE_STRANDED, SHUTTLE_ESCAPE)", edge.original_text)
		self.assertIsNone(edge.source_module_id)
		self.assertEqual("unattributed", edge.attribution)

	def test_bare_inline_marker_with_no_label(self) -> None:
		text = '\ticon="rat" // NOVA EDIT ADDITION\n'

		edges = parse_markers(text, frozenset())

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("addition", edge.edit_type)
		self.assertEqual("", edge.raw_label)
		self.assertEqual("unattributed", edge.attribution)

	def test_free_text_reason_with_no_module_id_is_unattributed(self) -> None:
		text = "'modular_nova', // NOVA EDIT ADDITION - Making the cutter actually work\n"

		edges = parse_markers(text, frozenset({"icon_cutter"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("unattributed", edge.attribution)
		self.assertIsNone(edge.source_module_id)
		self.assertEqual("Making the cutter actually work", edge.raw_label)

	def test_path_reference_resolves_when_module_exists(self) -> None:
		text = "// APHELION EDIT ADDITION BEGIN - See modular_nova/modules/self_destruct_sequence.\n"

		edges = parse_markers(text, frozenset({"self_destruct_sequence"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("APHELION", edge.owner)
		self.assertEqual("addition", edge.edit_type)
		self.assertEqual("self_destruct_sequence", edge.source_module_id)
		self.assertEqual("exact", edge.attribution)

	def test_path_reference_is_path_derived_when_module_does_not_exist(self) -> None:
		text = "// APHELION EDIT ADDITION BEGIN - See modular_nova/modules/self_destruct_sequence.\n"

		edges = parse_markers(text, frozenset())

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("self_destruct_sequence", edge.source_module_id)
		self.assertEqual("path-derived", edge.attribution)

	def test_bare_start_and_end_with_no_keyword_or_label(self) -> None:
		text = (
			"// APHELION EDIT START\n"
			"some_var = 1\n"
			"// APHELION EDIT END\n"
			"// NOVA EDIT START\n"
			"other_var = 2\n"
			"// NOVA EDIT END\n"
		)

		edges = parse_markers(text, frozenset())

		# each START yields one edge; each bare END is a no-op closer, not a second edge
		self.assertEqual(2, len(edges))
		self.assertEqual(["APHELION", "NOVA"], [edge.owner for edge in edges])
		for edge in edges:
			self.assertEqual("unspecified", edge.edit_type)
			self.assertEqual("unattributed", edge.attribution)

	def test_begin_is_treated_as_equivalent_to_start(self) -> None:
		text = "/* NOVA EDIT ADDITION START */\nsome_code()\n/* NOVA EDIT ADDITION END */\n"

		edges = parse_markers(text, frozenset())

		self.assertEqual(1, len(edges))
		self.assertEqual("addition", edges[0].edit_type)

	def test_define_addition_with_no_block(self) -> None:
		text = '#define POLL_IGNORE_MUTANT "mutant" // APHELION EDIT ADDITION - Mutated Abomination\n'

		edges = parse_markers(text, frozenset({"mutated_abomination"}))

		self.assertEqual(1, len(edges))
		edge = edges[0]
		self.assertEqual("APHELION", edge.owner)
		self.assertEqual("addition", edge.edit_type)
		# "Mutated" alone doesn't match the "mutated_abomination" module id -- correctly unattributed
		self.assertEqual("unattributed", edge.attribution)

	def test_no_marker_in_ordinary_line_returns_no_edges(self) -> None:
		text = "var/obj/item/gun/proc/shoot_live_shot(mob/living/user)\n\treturn\n"

		edges = parse_markers(text, frozenset())

		self.assertEqual([], edges)

	def test_multiple_markers_across_file_preserve_line_numbers(self) -> None:
		text = (
			"line one\n"
			"// NOVA EDIT ADDITION - reason a\n"
			"line three\n"
			"// APHELION EDIT REMOVAL - reason b\n"
		)

		edges = parse_markers(text, frozenset())

		self.assertEqual([2, 4], [edge.line_number for edge in edges])
		self.assertEqual(["addition", "removal"], [edge.edit_type for edge in edges])


if __name__ == "__main__":
	unittest.main()
