from __future__ import annotations

from webapp.tooling import ToolDefinition


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
	ToolDefinition(
		id="catalog-refresh",
		label="Refresh catalog",
		description="Recompile the BYOND catalog probe and refresh targets.json.",
		tool_root="tools/lore_editor",
		commands=(("catalog-refresh",),),
		game_repo_commands=frozenset({"catalog-refresh"}),
	),
	ToolDefinition(
		id="validate",
		label="Validate content",
		description="Validate lore JSON and check the generated DM artifact.",
		tool_root="tools/lore_editor",
		commands=(("validate", "--check-generated"),),
		game_repo_commands=frozenset({"validate"}),
	),
	ToolDefinition(
		id="generate",
		label="Generate DM",
		description="Regenerate the checked-in lore override DM artifact.",
		tool_root="tools/lore_editor",
		commands=(("generate",),),
	),
	ToolDefinition(
		id="refresh-validate",
		label="Refresh and validate",
		description="Refresh the BYOND catalog, then validate the resulting lore content.",
		tool_root="tools/lore_editor",
		commands=(("catalog-refresh",), ("validate", "--check-generated")),
		game_repo_commands=frozenset({"catalog-refresh", "validate"}),
	),
)
