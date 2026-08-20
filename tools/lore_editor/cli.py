from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
	from tools.lore_editor.catalog import compute_catalog_drift, read_current_targets, refresh_catalog
	from tools.lore_editor.export import apply_export, prepare_export
	from tools.lore_editor.generate import write_generated_dm
	from tools.lore_editor.source import load_corpus
	from tools.lore_editor.validation import validate_corpus
else:
	from .catalog import compute_catalog_drift, read_current_targets, refresh_catalog
	from .export import apply_export, prepare_export
	from .generate import write_generated_dm
	from .source import load_corpus
	from .validation import validate_corpus


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Validate and generate Aphelion lore-overhaul content.")
	subparsers = parser.add_subparsers(dest="command", required=True)

	validate_parser = subparsers.add_parser("validate", help="Validate lore source data without writing it.")
	validate_parser.add_argument("--repo-root", type=Path, required=True)
	validate_parser.add_argument("--game-repo", type=Path)
	validate_parser.add_argument("--check-generated", action="store_true")

	generate_parser = subparsers.add_parser("generate", help="Generate the checked-in DM artifact.")
	generate_parser.add_argument("--repo-root", type=Path, required=True)

	catalog_parser = subparsers.add_parser("catalog-refresh", help="Refresh the BYOND target catalog.")
	catalog_parser.add_argument("--repo-root", type=Path, required=True)
	catalog_parser.add_argument("--game-repo", type=Path)

	prepare_parser = subparsers.add_parser("prepare-export", help="Validate and stage a game-repository export.")
	prepare_parser.add_argument("--repo-root", type=Path, required=True)
	prepare_parser.add_argument("--game-repo", type=Path, required=True)
	prepare_parser.add_argument("--stage-root", type=Path)

	apply_parser = subparsers.add_parser("apply-export", help="Apply a prepared export to a clean game checkout.")
	apply_parser.add_argument("--stage", type=Path, required=True)
	apply_parser.add_argument("--game-repo", type=Path, required=True)

	return parser


def format_issues(issues: list) -> str:
	return "\n".join(f"- {issue.path}: {issue.message}" for issue in issues)


def validate_command(repo_root: Path, check_generated: bool, game_repo_root: Path | None = None) -> int:
	corpus = load_corpus(repo_root)
	issues = validate_corpus(repo_root, corpus, asset_root=game_repo_root)
	if issues:
		raise ValueError(f"Lore corpus validation failed:\n{format_issues(issues)}")
	if check_generated:
		write_generated_dm(repo_root, check_only=True)
	print("Lore content is valid.")
	return 0


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	repo_root = args.repo_root.resolve() if hasattr(args, "repo_root") else None
	try:
		if args.command == "validate":
			assert repo_root is not None
			return validate_command(repo_root, args.check_generated, args.game_repo.resolve() if args.game_repo else None)
		if args.command == "generate":
			assert repo_root is not None
			write_generated_dm(repo_root)
			print("Generated lore DM artifact.")
			return 0
		if args.command == "catalog-refresh":
			assert repo_root is not None
			old_targets = read_current_targets(repo_root)
			if args.game_repo:
				targets = refresh_catalog(repo_root, game_repo_root=args.game_repo.resolve())
			else:
				targets = refresh_catalog(repo_root)
			print(f"Refreshed lore target catalog ({len(targets)} targets).")
			entry_type_paths = frozenset(
				entry.type_path for entry in load_corpus(repo_root).entries if entry.type_path is not None
			)
			drift = compute_catalog_drift(old_targets, targets, entry_type_paths)
			if drift.removed_type_paths:
				print(f"Removed from the game repository ({len(drift.removed_type_paths)}):")
				for type_path in drift.removed_type_paths:
					print(f"  - {type_path}")
			if drift.changed_type_paths:
				print(f"Changed in the game repository ({len(drift.changed_type_paths)}):")
				for type_path in drift.changed_type_paths:
					print(f"  - {type_path}")
			if drift.stale_entry_type_paths:
				print(f"Overrides affected by these changes ({len(drift.stale_entry_type_paths)}):")
				for type_path in drift.stale_entry_type_paths:
					print(f"  - {type_path}")
			return 0
		if args.command == "prepare-export":
			assert repo_root is not None
			stage_root = args.stage_root or (repo_root / "tools/lore_editor/stages")
			prepared = prepare_export(repo_root, args.game_repo.resolve(), stage_root)
			print(f"Prepared export stage: {prepared.directory}")
			return 0
		if args.command == "apply-export":
			artifact_path = apply_export(args.stage, args.game_repo.resolve())
			print(f"Applied generated lore artifact: {artifact_path}")
			return 0
	except (OSError, ValueError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1

	return 2


if __name__ == "__main__":
	raise SystemExit(main())
