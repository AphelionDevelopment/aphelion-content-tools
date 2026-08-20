from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceLayout:
	standalone: bool
	targets_path: Path
	entities_root: Path
	groups_path: Path
	reviews_path: Path
	content_groups_root: Path
	content_reviews_root: Path
	content_assignments_root: Path
	generated_dm_path: Path

	@classmethod
	def from_root(cls, repo_root: Path) -> "WorkspaceLayout":
		resolved_root = repo_root.resolve()
		standalone = any(path.is_dir() for path in (
			resolved_root / "tools" / "lore_editor" / "catalog",
			resolved_root / "tools" / "lore_editor" / "content",
		))
		if standalone:
			content_root = Path("tools/lore_editor/content")
			return cls(
				standalone=True,
				targets_path=Path("tools/lore_editor/catalog/targets.json"),
				entities_root=content_root / "overrides",
				groups_path=content_root / "groups.json",
				reviews_path=content_root / "reviews.json",
				content_groups_root=content_root / "groups",
				content_reviews_root=content_root / "reviews",
				content_assignments_root=content_root / "assignments",
				generated_dm_path=Path("tools/lore_editor/stages/current/generated_lore_overrides.dm"),
			)
		return cls(
			standalone=False,
			targets_path=Path("config/aphelion/lore_overhaul/targets.json"),
			entities_root=Path("config/aphelion/lore_overhaul/entities"),
			groups_path=Path("config/aphelion/lore_overhaul/groups.json"),
			reviews_path=Path("config/aphelion/lore_overhaul/reviews.json"),
			content_groups_root=Path("config/aphelion/lore_overhaul/entities"),
			content_reviews_root=Path("config/aphelion/lore_overhaul/entities"),
			content_assignments_root=Path("config/aphelion/lore_overhaul/entities"),
			generated_dm_path=Path("modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"),
		)
