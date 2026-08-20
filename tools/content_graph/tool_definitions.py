from __future__ import annotations

from webapp.tooling import ToolDefinition


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
	ToolDefinition(
		id="scan-content",
		label="Scan modular content",
		description="Walk the game checkout's modular_nova/modular_aphelion modules, master_files overrides, and NOVA/APHELION EDIT markers, and cache a content graph.",
		tool_root="tools/content_graph",
		commands=(("scan",),),
		game_repo_commands=frozenset({"scan"}),
	),
)
