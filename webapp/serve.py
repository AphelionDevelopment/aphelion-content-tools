from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
	sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
	from webapp.server import create_server
else:
	from .server import create_server


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Run the local Aphelion Content Tools web app.")
	parser.add_argument("--repo-root", type=Path, required=True)
	parser.add_argument("--game-repo", type=Path)
	parser.add_argument("--port", type=int, default=0)
	args = parser.parse_args(argv)

	try:
		server = create_server(args.repo_root, args.port, game_repo_root=args.game_repo)
	except (OSError, ValueError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1

	print(f"LORE_EDITOR_URL=http://127.0.0.1:{server.server_address[1]}", flush=True)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		return 0
	finally:
		server.server_close()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
