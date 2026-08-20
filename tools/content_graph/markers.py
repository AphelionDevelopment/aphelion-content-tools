from __future__ import annotations

from dataclasses import dataclass
import re


EDIT_TYPES = frozenset(("addition", "removal", "change", "unspecified"))
ATTRIBUTIONS = frozenset(("exact", "path-derived", "unattributed"))

_KIND_BY_TOKEN = {"ADDITION": "addition", "REMOVAL": "removal", "CHANGE": "change"}

_LINE_PATTERN = re.compile(
	r"(?P<owner>NOVA|APHELION)\s+EDIT"
	r"(?:\s+(?P<kind>ADDITION|REMOVAL|CHANGE))?"
	r"(?:\s+(?P<terminator>START|BEGIN|END))?"
	r"(?:\s*-\s*(?P<label>.+))?"
	r"\s*(?:\*/)?\s*$"
)
_ORIGINAL_PATTERN = re.compile(r"^ORIGINAL:\s*(.*)$", re.IGNORECASE)
_PATH_MODULE_PATTERN = re.compile(r"modular_(?:nova|aphelion)/modules/([A-Za-z0-9_-]+)")
_LEADING_TOKEN_PATTERN = re.compile(r"^\(?([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class MarkerEdge:
	owner: str
	edit_type: str
	line_number: int
	source_module_id: str | None
	attribution: str
	raw_label: str
	original_text: str | None
	line_text: str


def _strip_trailing_comment_close(label: str) -> str:
	label = label.strip()
	if label.endswith("*/"):
		label = label[:-2].rstrip()
	return label


def _extract_module_id(label_for_attribution: str, known_module_ids_by_fold: dict[str, str]) -> tuple[str | None, str]:
	if not label_for_attribution:
		return None, "unattributed"
	path_match = _PATH_MODULE_PATTERN.search(label_for_attribution)
	if path_match is not None:
		candidate = path_match.group(1)
		resolved = known_module_ids_by_fold.get(candidate.casefold())
		if resolved is not None:
			return resolved, "exact"
		return candidate, "path-derived"
	leading_match = _LEADING_TOKEN_PATTERN.match(label_for_attribution)
	if leading_match is not None:
		candidate = leading_match.group(1)
		resolved = known_module_ids_by_fold.get(candidate.casefold())
		if resolved is not None:
			return resolved, "exact"
	return None, "unattributed"


def render_marker_line(line: str, new_label: str) -> str:
	"""Return `line` with its marker label replaced by `new_label`, preserving everything else.

	Reuses `_LINE_PATTERN` (the same grammar `parse_markers` reads) to locate the label span and
	substitute it byte-for-byte around the edges. If the marker currently has no label at all (e.g. a
	bare `// NOVA EDIT START`), one is inserted right after the last matched marker token. A trailing
	`*/` comment-close captured inside the label (a same-line removal-block close) is preserved, though
	its exact surrounding whitespace is normalized to a single space rather than reproduced verbatim.

	Raises ValueError if `line` doesn't contain a recognizable NOVA/APHELION EDIT marker.
	"""
	match = _LINE_PATTERN.search(line)
	if match is None:
		raise ValueError("Line does not contain a recognizable NOVA/APHELION EDIT marker.")
	new_label = new_label.strip()
	if match.group("label") is not None:
		label_start, label_end = match.span("label")
		has_trailing_close = match.group("label").rstrip().endswith("*/")
		replacement = new_label + " */" if has_trailing_close else new_label
		return line[:label_start] + replacement + line[label_end:]
	insertion_point = (
		match.end("terminator") if match.group("terminator")
		else match.end("kind") if match.group("kind")
		else match.end("owner")
	)
	return line[:insertion_point] + " - " + new_label + line[insertion_point:]


def parse_markers(text: str, known_module_ids: frozenset[str]) -> list[MarkerEdge]:
	"""Parse NOVA EDIT / APHELION EDIT marker comments out of DreamMaker source text.

	Tolerates the real-world format inconsistencies found in Meridian-Rift: START and BEGIN used
	interchangeably as block openers, single-line markers with no START/END at all, markers wrapped in
	either `//` or `/* */`, and module attribution given as a free-text reason, a leading identifier
	token, or a `modular_nova/modules/<id>` path reference instead of a clean module id.
	"""
	known_module_ids_by_fold = {module_id.casefold(): module_id for module_id in known_module_ids}
	edges: list[MarkerEdge] = []
	for line_number, line in enumerate(text.splitlines(), start=1):
		match = _LINE_PATTERN.search(line)
		if match is None:
			continue
		if match.group("terminator") == "END":
			continue
		owner = match.group("owner")
		edit_type = _KIND_BY_TOKEN.get(match.group("kind"), "unspecified")
		raw_label = _strip_trailing_comment_close(match.group("label") or "")

		original_text: str | None = None
		label_for_attribution = raw_label
		original_match = _ORIGINAL_PATTERN.match(raw_label)
		if original_match is not None:
			original_text = original_match.group(1).strip() or None
			label_for_attribution = ""

		source_module_id, attribution = _extract_module_id(label_for_attribution, known_module_ids_by_fold)

		edges.append(MarkerEdge(
			owner=owner,
			edit_type=edit_type,
			line_number=line_number,
			source_module_id=source_module_id,
			attribution=attribution,
			raw_label=raw_label,
			original_text=original_text,
			line_text=line,
		))
	return edges
