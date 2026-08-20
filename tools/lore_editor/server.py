from __future__ import annotations

import json
from dataclasses import asdict
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


WEB_ROOT = Path(__file__).resolve().parent / "web"


def _query_int(query: dict[str, list[str]], name: str, *, default: int | None = None, minimum: int = 0) -> int | None:
	value = query.get(name, [None])[0]
	if value is None or value == "":
		return default
	try:
		parsed_value = int(value)
	except ValueError as exc:
		raise ValueError(f"Query parameter '{name}' must be an integer.") from exc
	if parsed_value < minimum:
		raise ValueError(f"Query parameter '{name}' must be at least {minimum}.")
	return parsed_value


def _load_api_functions():
	if __package__ in (None, ""):
		from tools.lore_editor.api import catalog_response, generate_output, groups_response, icon_files_response, icon_states_response, list_entries_response, list_icon_choices, list_review_response
		from tools.lore_editor.api import create_entry, list_entity_files, save_group_response, save_review_response
		from tools.lore_editor.api import save_entry, validate_entries, validate_entry
		from tools.lore_editor.tooling import get_tool_run, list_tools, start_tool
		from tools.lore_editor.icon_preview import IconPreviewNotFound, render_icon_preview
	else:
		from .api import catalog_response, generate_output, groups_response, icon_files_response, icon_states_response, list_entries_response, list_icon_choices, list_review_response
		from .api import create_entry, list_entity_files, save_group_response, save_review_response
		from .api import save_entry, validate_entries, validate_entry
		from .tooling import get_tool_run, list_tools, start_tool
		from .icon_preview import IconPreviewNotFound, render_icon_preview
	return catalog_response, generate_output, list_entries_response, list_icon_choices, save_entry, validate_entries, validate_entry, IconPreviewNotFound, render_icon_preview, list_review_response, groups_response, save_group_response, save_review_response, create_entry, list_entity_files, list_tools, start_tool, get_tool_run, icon_files_response, icon_states_response


def _load_git_functions():
	if __package__ in (None, ""):
		from tools.lore_editor.git_adapter import create_branch, open_in_github_desktop, repository_status, stage_and_commit
	else:
		from .git_adapter import create_branch, open_in_github_desktop, repository_status, stage_and_commit
	return create_branch, repository_status, stage_and_commit, open_in_github_desktop


def _load_export_functions():
	if __package__ in (None, ""):
		from tools.lore_editor.export import apply_export, prepare_export
	else:
		from .export import apply_export, prepare_export
	return prepare_export, apply_export


class LoreEditorServer(ThreadingHTTPServer):
	allow_reuse_address = True

	def __init__(self, server_address: tuple[str, int], repo_root: Path, game_repo_root: Path | None = None):
		self.repo_root = repo_root.resolve()
		self.game_repo_root = (game_repo_root or repo_root).resolve()
		super().__init__(server_address, LoreEditorRequestHandler)


class LoreEditorRequestHandler(BaseHTTPRequestHandler):
	server: LoreEditorServer
	MAX_REQUEST_BYTES = 1_000_000

	def log_message(self, format: str, *args: object) -> None:
		return

	def send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
		self.send_response(status)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
		body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
		self.send_bytes(body, "application/json", status)

	def send_error_json(self, status: HTTPStatus, message: str) -> None:
		self.send_json({"error": message}, status)

	def read_json_body(self) -> object:
		try:
			content_length = int(self.headers.get("Content-Length", "0"))
		except ValueError as exc:
			raise ValueError("Content-Length must be an integer.") from exc
		if content_length < 0 or content_length > self.MAX_REQUEST_BYTES:
			raise ValueError("Request body is too large.")
		try:
			return json.loads(self.rfile.read(content_length))
		except json.JSONDecodeError as exc:
			raise ValueError(f"Request body is not valid JSON: {exc.msg}.") from exc

	def repository_root(self, repository_name: str) -> Path:
		if repository_name == "tool":
			return self.server.repo_root
		if repository_name == "game":
			return self.server.game_repo_root
		raise ValueError("Repository must be 'tool' or 'game'.")

	def export_stage_root(self) -> Path:
		return (self.server.repo_root / "tools/lore_editor/stages").resolve()

	def export_stage_path(self, stage_name: str) -> Path:
		if not stage_name or Path(stage_name).is_absolute():
			raise ValueError("Export stage must be a non-empty repository-relative path.")
		stage_root = self.export_stage_root()
		stage_path = (stage_root / Path(stage_name)).resolve()
		if not stage_path.is_relative_to(stage_root) or not stage_path.is_dir():
			raise ValueError("Export stage is not inside the local staging directory.")
		return stage_path

	def serve_static(self, filename: str, content_type: str) -> None:
		path = (WEB_ROOT / filename).resolve()
		if not path.is_relative_to(WEB_ROOT) or not path.is_file():
			self.send_error_json(HTTPStatus.NOT_FOUND, "Resource not found.")
			return
		self.send_bytes(path.read_bytes(), content_type)

	def do_GET(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path == "/":
			self.serve_static("index.html", "text/html; charset=utf-8")
			return
		if parsed.path == "/app.js":
			self.serve_static("app.js", "text/javascript; charset=utf-8")
			return
		if parsed.path == "/styles.css":
			self.serve_static("styles.css", "text/css; charset=utf-8")
			return
		if parsed.path in {"/favicon.svg", "/favicon.ico"}:
			self.serve_static("favicon.svg", "image/svg+xml")
			return
		if parsed.path == "/api/health":
			self.send_json({"ok": True, "service": "lore-editor"})
			return
		if parsed.path == "/api/git/status":
			try:
				query = parse_qs(parsed.query)
				repository_name = query.get("repository", ["tool"])[0]
				_repository_status = _load_git_functions()[1]
				status = _repository_status(self.repository_root(repository_name))
				self.send_json(asdict(status) | {"conflicted": status.conflicted})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/export/stages":
			try:
				stage_root = self.export_stage_root()
				stages: list[dict[str, object]] = []
				if stage_root.is_dir():
					for manifest_path in sorted(stage_root.glob("*/manifest.json"), key=lambda path: path.parent.name):
						try:
							manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
						except (OSError, json.JSONDecodeError):
							continue
						stages.append({"stage": manifest_path.parent.name, "manifest": manifest})
				self.send_json({"stages": stages})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/catalog":
			try:
				catalog_response = _load_api_functions()[0]
				self.send_json(catalog_response(self.server.repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/entries":
			try:
				list_entries_response = _load_api_functions()[2]
				query = parse_qs(parsed.query)
				self.send_json(
					list_entries_response(
						self.server.repo_root,
						query=query.get("q", [""])[0],
						category=query.get("category", [""])[0],
						asset_root=self.server.game_repo_root,
					)
				)
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/review":
			try:
				list_review_response = _load_api_functions()[9]
				query = parse_qs(parsed.query)
				self.send_json(
					list_review_response(
						self.server.repo_root,
						query=query.get("q", [""])[0],
						category=query.get("category", [""])[0],
						groups=tuple(query.get("group", [])),
						statuses=tuple(query.get("status", [])),
						sort=query.get("sort", ["name"])[0],
						include_directional=query.get("include_directional", ["false"])[0].casefold() == "true",
						include_redundant=query.get("include_redundant", ["false"])[0].casefold() == "true",
						offset=_query_int(query, "offset", default=0) or 0,
						limit=_query_int(query, "limit", minimum=1),
						asset_root=self.server.game_repo_root,
					)
				)
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/groups":
			try:
				groups_response = _load_api_functions()[10]
				self.send_json(groups_response(self.server.repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/entity-files":
			try:
				list_entity_files = _load_api_functions()[14]
				self.send_json({"files": list_entity_files(self.server.repo_root)})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/tools":
			try:
				list_tools = _load_api_functions()[15]
				self.send_json({"tools": list_tools()})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/icon-files":
			try:
				icon_files_response = _load_api_functions()[18]
				self.send_json(icon_files_response(self.server.repo_root, asset_root=self.server.game_repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		tool_run_prefix = "/api/tools/runs/"
		if parsed.path.startswith(tool_run_prefix):
			try:
				get_tool_run = _load_api_functions()[17]
				self.send_json(get_tool_run(unquote(parsed.path[len(tool_run_prefix):])))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/icons":
			try:
				list_icon_choices = _load_api_functions()[3]
				self.send_json({"icons": list_icon_choices(self.server.repo_root, asset_root=self.server.game_repo_root)})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/icon-states":
			try:
				query = parse_qs(parsed.query)
				relative_file = query.get("file", [""])[0]
				if not relative_file:
					raise ValueError("Icon state lookup requires a file query parameter.")
				icon_states_response = _load_api_functions()[19]
				self.send_json(icon_states_response(self.server.repo_root, relative_file, asset_root=self.server.game_repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/icon":
			try:
				_query = parse_qs(parsed.query)
				relative_file = _query.get("file", [""])[0]
				state = _query.get("state", [""])[0]
				if not relative_file or not state:
					raise ValueError("Icon preview requires file and state query parameters.")
				_render_icon_preview = _load_api_functions()[8]
				self.send_bytes(
					_render_icon_preview(self.server.game_repo_root, relative_file, state),
					"image/png",
				)
			except _load_api_functions()[7] as exc:
				self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		self.send_error_json(HTTPStatus.NOT_FOUND, "Resource not found.")

	def do_POST(self) -> None:
		parsed = urlparse(self.path)
		if parsed.path == "/api/export/prepare":
			try:
				if self.headers.get("Content-Length"):
					payload = self.read_json_body()
					if not isinstance(payload, dict):
						raise ValueError("Export preparation request must be a JSON object.")
				_prepare_export, _apply_export = _load_export_functions()
				prepared = _prepare_export(
					self.server.repo_root,
					self.server.game_repo_root,
					self.export_stage_root(),
				)
				stage_root = self.export_stage_root()
				self.send_json({
					"prepared": True,
					"stage": prepared.directory.resolve().relative_to(stage_root).as_posix(),
					"artifact": prepared.artifact_path.resolve().relative_to(prepared.directory.resolve()).as_posix(),
					"manifest": prepared.manifest.to_dict(),
				})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/export/apply":
			try:
				payload = self.read_json_body()
				if not isinstance(payload, dict) or not isinstance(payload.get("stage"), str):
					raise ValueError("Export application requires a string stage.")
				_prepare_export, _apply_export = _load_export_functions()
				artifact_path = _apply_export(
					self.export_stage_path(payload["stage"]),
					self.server.game_repo_root,
				)
				opened_in_github_desktop = False
				github_desktop_error = None
				try:
					_open_desktop = _load_git_functions()[3]
					_open_desktop(self.server.game_repo_root)
					opened_in_github_desktop = True
				except (OSError, ValueError) as desktop_exc:
					github_desktop_error = str(desktop_exc)
				self.send_json({
					"applied": True,
					"artifact": artifact_path.resolve().relative_to(self.server.game_repo_root.resolve()).as_posix(),
					"opened_in_github_desktop": opened_in_github_desktop,
					"github_desktop_error": github_desktop_error,
				})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/git/branch":
			try:
				payload = self.read_json_body()
				if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
					raise ValueError("Branch request requires a string name.")
				repository_name = payload.get("repository", "tool")
				if not isinstance(repository_name, str):
					raise ValueError("Branch request repository must be a string.")
				_create_branch = _load_git_functions()[0]
				_create_branch(self.repository_root(repository_name), payload["name"])
				self.send_json({"repository": repository_name, "branch": payload["name"]})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/git/commit":
			try:
				payload = self.read_json_body()
				if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
					raise ValueError("Commit request requires a string message.")
				paths = payload.get("paths")
				if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
					raise ValueError("Commit request paths must be an array of strings.")
				repository_name = payload.get("repository", "tool")
				if not isinstance(repository_name, str):
					raise ValueError("Commit request repository must be a string.")
				_commit = _load_git_functions()[2]
				commit_sha = _commit(self.repository_root(repository_name), tuple(paths), payload["message"])
				self.send_json({"repository": repository_name, "commit": commit_sha})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/git/open":
			try:
				payload = self.read_json_body()
				repository_name = payload.get("repository", "tool") if isinstance(payload, dict) else "tool"
				if not isinstance(repository_name, str):
					raise ValueError("Open request repository must be a string.")
				_open_desktop = _load_git_functions()[3]
				_open_desktop(self.repository_root(repository_name))
				self.send_json({"repository": repository_name, "opened": True})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/generate":
			try:
				generate_output = _load_api_functions()[1]
				self.send_json(generate_output(self.server.repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/groups":
			try:
				payload = self.read_json_body()
				save_group_response = _load_api_functions()[11]
				self.send_json(save_group_response(self.server.repo_root, payload))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path == "/api/entries":
			try:
				payload = self.read_json_body()
				if not isinstance(payload, dict) or not isinstance(payload.get("source_file"), str):
					raise ValueError("Create request must contain a string source_file.")
				create_entry = _load_api_functions()[13]
				created_entry = create_entry(
					self.server.repo_root,
					source_file=payload["source_file"],
					entry=payload.get("entry"),
					asset_root=self.server.game_repo_root,
				)
				self.send_json({"saved": True, "created": True, "entry": created_entry, "issues": []})
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		tool_prefix = "/api/tools/"
		if parsed.path.startswith(tool_prefix):
			tool_id = unquote(parsed.path[len(tool_prefix):])
			if tool_id.startswith("runs/"):
				self.send_error_json(HTTPStatus.NOT_FOUND, "Tool runs are read-only.")
				return
			try:
				start_tool = _load_api_functions()[16]
				self.send_json(start_tool(self.server.repo_root, tool_id, game_repo_root=self.server.game_repo_root))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		if parsed.path != "/api/validate":
			self.send_error_json(HTTPStatus.NOT_FOUND, "Resource not found.")
			return
		try:
			payload = self.read_json_body()
			if not isinstance(payload, dict):
				raise ValueError("Request body must be a JSON object.")
			source_file = payload.get("source_file")
			if source_file is not None and not isinstance(source_file, str):
				raise ValueError("Request source_file must be a string when provided.")
			if "entries" in payload:
				entries = payload.get("entries")
				if not isinstance(entries, list):
					raise ValueError("Request entries must be a JSON array.")
				validate_entries = _load_api_functions()[5]
				self.send_json(validate_entries(self.server.repo_root, entries=entries, source_file=source_file, asset_root=self.server.game_repo_root))
			else:
				if not isinstance(source_file, str):
					raise ValueError("Request must contain a string source_file.")
				validate_entry = _load_api_functions()[6]
				self.send_json(validate_entry(self.server.repo_root, source_file=source_file, entry=payload.get("entry"), asset_root=self.server.game_repo_root))
		except (OSError, ValueError) as exc:
			self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

	def do_PUT(self) -> None:
		parsed = urlparse(self.path)
		review_prefix = "/api/reviews/"
		if parsed.path.startswith(review_prefix):
			type_path = unquote(parsed.path[len(review_prefix):])
			try:
				payload = self.read_json_body()
				save_review_response = _load_api_functions()[12]
				self.send_json(save_review_response(self.server.repo_root, type_path, payload))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		group_prefix = "/api/groups/"
		if parsed.path.startswith(group_prefix):
			group_id = unquote(parsed.path[len(group_prefix):])
			try:
				payload = self.read_json_body()
				if not isinstance(payload, dict):
					raise ValueError("Group payload must be a JSON object.")
				payload["id"] = group_id
				save_group_response = _load_api_functions()[11]
				self.send_json(save_group_response(self.server.repo_root, payload))
			except (OSError, ValueError) as exc:
				self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
			return
		prefix = "/api/entries/"
		if not parsed.path.startswith(prefix):
			self.send_error_json(HTTPStatus.NOT_FOUND, "Resource not found.")
			return
		entry_id = unquote(parsed.path[len(prefix):])
		if not entry_id or "/" in entry_id:
			self.send_error_json(HTTPStatus.BAD_REQUEST, "A single lore entry id is required.")
			return
		try:
			payload = self.read_json_body()
			if not isinstance(payload, dict):
				raise ValueError("Request body must be a JSON object.")
			source_file = payload.get("source_file")
			if not isinstance(source_file, str):
				raise ValueError("Request must contain a string source_file.")
			save_entry = _load_api_functions()[4]
			saved_entry = save_entry(
				self.server.repo_root,
				entry_id=entry_id,
				source_file=source_file,
				entry=payload.get("entry"),
				asset_root=self.server.game_repo_root,
			)
			self.send_json({"saved": True, "entry": saved_entry, "issues": []})
		except (OSError, ValueError) as exc:
			self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))


def create_server(repo_root: Path, port: int = 0, *, game_repo_root: Path | None = None) -> LoreEditorServer:
	return LoreEditorServer(("127.0.0.1", port), repo_root, game_repo_root)
