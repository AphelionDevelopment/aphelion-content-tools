from __future__ import annotations


def edits_for_core_file(graph: dict[str, object], core_file: str) -> list[dict[str, object]]:
	"""All marker edges touching `core_file`, resolved and unresolved alike."""
	edits: list[dict[str, object]] = []
	for edge in graph["edges"]:
		if edge.get("relation") != "marker_edit":
			continue
		if edge.get("target") != f"core_file:{core_file}":
			continue
		edits.append({**edge, "resolved": True})
	for marker in graph["unresolved_markers"]:
		if marker.get("core_file") != core_file:
			continue
		edits.append({**marker, "resolved": False})
	edits.sort(key=lambda edit: edit.get("line_number") or 0)
	return edits


def modules_missing_readme(graph: dict[str, object]) -> list[dict[str, object]]:
	return [node for node in graph["nodes"] if node.get("kind") == "module" and not node.get("has_readme")]


def unresolved_markers(graph: dict[str, object]) -> list[dict[str, object]]:
	return list(graph["unresolved_markers"])
