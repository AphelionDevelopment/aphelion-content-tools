from __future__ import annotations

from webapp.tooling import ToolDefinition


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
	ToolDefinition(
		id="scan-content",
		label="Scan modular content",
		description=(
			"Walk the entire game checkout -- modular_nova/modular_aphelion modules, master_files "
			"overrides, NOVA/APHELION EDIT markers, and every other Git-tracked file -- and cache the "
			"result as the content graph the Content Graph page renders from. This can take a while on "
			"the full ~25,000-file checkout. Run it after pulling new game-repo changes, after editing "
			"marker comments or master_files overrides directly, or whenever the graph or Unresolved "
			"Markers list looks stale; nothing else refreshes this cache automatically."
		),
		tool_root="tools/content_graph",
		commands=(("scan",),),
		game_repo_commands=frozenset({"scan"}),
	),
)
