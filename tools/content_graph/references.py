from __future__ import annotations


def find_text_references(texts_by_fragment: dict[str, str], id_by_fragment: dict[str, str]) -> tuple[tuple[str, str], ...]:
	"""Return (source_id, target_id) pairs where the target's fragment appears literally in the source's text.

	Best-effort textual scan -- no real DM/BYOND parsing -- so this only catches references written as a
	literal path or module-id string (e.g. a comment mentioning `modular_nova/modules/other_module`), the
	same class of heuristic already used for marker attribution elsewhere in this scanner. `texts_by_fragment`
	and `id_by_fragment` share the same fragment keys (a module's path, or a core file's path); a fragment
	missing from `id_by_fragment` is skipped as a source, and self-references are excluded.
	"""
	edges: list[tuple[str, str]] = []
	for source_fragment, text in texts_by_fragment.items():
		if not text:
			continue
		source_id = id_by_fragment.get(source_fragment)
		if source_id is None:
			continue
		for target_fragment, target_id in id_by_fragment.items():
			if target_fragment == source_fragment:
				continue
			if target_fragment in text:
				edges.append((source_id, target_id))
	return tuple(edges)
