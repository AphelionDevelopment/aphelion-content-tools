from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
	from tools.content_graph.graph import scan_and_cache_content_graph
else:
	from .graph import scan_and_cache_content_graph


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Scan a game checkout's modular content and cache a content graph.")
	subparsers = parser.add_subparsers(dest="command", required=True)

	scan_parser = subparsers.add_parser("scan", help="Scan the game checkout's modular content and cache a content graph.")
	scan_parser.add_argument("--repo-root", type=Path, required=True)
	scan_parser.add_argument("--game-repo", type=Path, required=True)

	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		if args.command == "scan":
			manifest = scan_and_cache_content_graph(args.repo_root.resolve(), args.game_repo.resolve())
			print(
				f"Scanned modular content: {manifest.module_count} modules, "
				f"{manifest.master_files_count} master_files overrides, {manifest.marker_count} markers "
				f"({manifest.node_count} nodes, {manifest.edge_count} edges)."
			)
			return 0
	except (OSError, ValueError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1

	return 2


if __name__ == "__main__":
	raise SystemExit(main())
