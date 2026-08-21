from __future__ import annotations

from webapp.tooling import ToolDefinition


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
	ToolDefinition(
		id="catalog-refresh",
		label="Refresh catalog",
		description=(
			"Recompile the BYOND catalog probe against the game checkout and rebuild targets.json, the "
			"snapshot of every reviewable type the Lore Editor's Catalog list is built from. Run this "
			"after pulling new upstream/game changes, or after the game checkout's DM code changed in a "
			"way that could add, remove, or rename reviewable types — otherwise the Catalog can drift out "
			"of sync with what actually compiles in the game repo."
		),
		tool_root="tools/lore_editor",
		commands=(("catalog-refresh",),),
		game_repo_commands=frozenset({"catalog-refresh"}),
	),
	ToolDefinition(
		id="validate",
		label="Validate content",
		description=(
			"Check every lore override JSON record for structural and reference errors (missing base "
			"types, broken icon/group references, malformed special-description rules), then confirm the "
			"checked-in generated DM artifact still matches what the current overrides would produce. Run "
			"this before preparing a Game Repository Export, or any time after hand-editing override JSON "
			"files outside the Lore Editor UI, to catch mistakes before they reach the game checkout."
		),
		tool_root="tools/lore_editor",
		commands=(("validate", "--check-generated"),),
		game_repo_commands=frozenset({"validate"}),
	),
	ToolDefinition(
		id="generate",
		label="Generate DM",
		description=(
			"Regenerate the checked-in lore override DM artifact from the current override JSON records, "
			"without touching the game checkout. Useful for previewing what a Game Repository Export would "
			"produce, or refreshing the artifact locally after editing overrides, before running Validate "
			"or preparing an export."
		),
		tool_root="tools/lore_editor",
		commands=(("generate",),),
	),
	ToolDefinition(
		id="refresh-validate",
		label="Refresh and validate",
		description=(
			"Run Refresh catalog and Validate content back to back — the combination you want before "
			"trusting the Catalog is current and every override in it is still valid. A good first step "
			"after pulling new game-repo changes, and the safest check to run right before preparing a "
			"Game Repository Export."
		),
		tool_root="tools/lore_editor",
		commands=(("catalog-refresh",), ("validate", "--check-generated")),
		game_repo_commands=frozenset({"catalog-refresh", "validate"}),
	),
)
