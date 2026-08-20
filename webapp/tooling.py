from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys
import threading
import uuid
from pathlib import Path


MAX_OUTPUT_CHARACTERS = 64_000
MAX_LOG_CHARACTERS = 1_000_000
LOG_ROOT = Path("tools/logs")


@dataclass(frozen=True)
class ToolDefinition:
	id: str
	label: str
	description: str
	tool_root: str
	commands: tuple[tuple[str, ...], ...]
	game_repo_commands: frozenset[str] = frozenset()


_RUNS: dict[str, dict[str, object]] = {}
_RUNS_LOCK = threading.Lock()


def list_tools(definitions: tuple[ToolDefinition, ...]) -> list[dict[str, str]]:
	return [
		{"id": definition.id, "label": definition.label, "description": definition.description}
		for definition in definitions
	]


def _find_definition(definitions: tuple[ToolDefinition, ...], tool_id: str) -> ToolDefinition:
	for definition in definitions:
		if definition.id == tool_id:
			return definition
	raise ValueError(f"Unknown tool '{tool_id}'.")


def build_tool_command(
	repo_root: Path,
	definition: ToolDefinition,
	command_index: int = 0,
	*,
	game_repo_root: Path | None = None,
) -> list[str]:
	if command_index < 0 or command_index >= len(definition.commands):
		raise ValueError(f"Tool '{definition.id}' has no command at index {command_index}.")
	resolved_root = repo_root.resolve()
	cli_path = (resolved_root / definition.tool_root / "cli.py").resolve()
	if not cli_path.is_relative_to(resolved_root):
		raise ValueError("Tool CLI must remain inside the repository root.")
	command = [sys.executable, str(cli_path), *definition.commands[command_index], "--repo-root", str(resolved_root)]
	if game_repo_root is not None and any(
		command_name in definition.game_repo_commands for command_name in definition.commands[command_index]
	):
		command.extend(("--game-repo", str(game_repo_root.resolve())))
	return command


def _append_log(repo_root: Path, run_id: str, text: str) -> None:
	log_path = repo_root.resolve() / LOG_ROOT / f"{run_id}.log"
	try:
		log_path.parent.mkdir(parents=True, exist_ok=True)
		if log_path.exists() and log_path.stat().st_size >= MAX_LOG_CHARACTERS:
			return
		with log_path.open("a", encoding="utf-8", newline="") as log_file:
			log_file.write(text)
	except OSError:
		return


def _append_output(repo_root: Path, run_id: str, text: str) -> None:
	with _RUNS_LOCK:
		run = _RUNS.get(run_id)
		if run is None:
			return
		current_output = str(run.get("output", ""))
		run["output"] = (current_output + text)[-MAX_OUTPUT_CHARACTERS:]
	_append_log(repo_root, run_id, text)


def _execute_tool(repo_root: Path, run_id: str, definition: ToolDefinition, game_repo_root: Path | None) -> None:
	with _RUNS_LOCK:
		_RUNS[run_id]["status"] = "running"
	_append_output(repo_root, run_id, f"Starting {definition.id}.\n")
	try:
		for command_index, _command in enumerate(definition.commands):
			command = build_tool_command(repo_root, definition, command_index, game_repo_root=game_repo_root)
			_append_output(repo_root, run_id, f"Command {command_index + 1}: {subprocess.list2cmdline(command)}\n")
			process = subprocess.Popen(
				command,
				cwd=str(repo_root.resolve()),
				stdin=subprocess.DEVNULL,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				encoding="utf-8",
				errors="replace",
				shell=False,
			)
			if process.stdout is not None:
				for line in process.stdout:
					_append_output(repo_root, run_id, line)
				process.stdout.close()
			return_code = process.wait()
			if return_code != 0:
				_append_output(repo_root, run_id, f"Command exited with code {return_code}.\n")
				with _RUNS_LOCK:
					_RUNS[run_id]["status"] = "failed"
					_RUNS[run_id]["exit_code"] = return_code
				return
		with _RUNS_LOCK:
			_RUNS[run_id]["status"] = "succeeded"
			_RUNS[run_id]["exit_code"] = 0
		_append_output(repo_root, run_id, "Completed successfully.\n")
	except Exception as exc:
		_append_output(repo_root, run_id, f"error: {exc}\n")
		with _RUNS_LOCK:
			_RUNS[run_id]["status"] = "failed"
			_RUNS[run_id]["exit_code"] = None


def start_tool(
	repo_root: Path,
	definitions: tuple[ToolDefinition, ...],
	tool_id: str,
	*,
	game_repo_root: Path | None = None,
) -> dict[str, object]:
	definition = _find_definition(definitions, tool_id)
	run_id = uuid.uuid4().hex
	log_path = LOG_ROOT / f"{run_id}.log"
	with _RUNS_LOCK:
		_RUNS[run_id] = {
			"run_id": run_id,
			"tool_id": tool_id,
			"status": "queued",
			"output": "",
			"exit_code": None,
			"log_path": log_path.as_posix(),
		}
	_append_log(repo_root.resolve(), run_id, f"Queued {tool_id}.\n")
	thread = threading.Thread(
		target=_execute_tool,
		args=(repo_root.resolve(), run_id, definition, game_repo_root.resolve() if game_repo_root else None),
		daemon=True,
	)
	thread.start()
	return get_tool_run(run_id)


def get_tool_run(run_id: str) -> dict[str, object]:
	with _RUNS_LOCK:
		if run_id not in _RUNS:
			raise ValueError(f"Unknown tool run '{run_id}'.")
		return dict(_RUNS[run_id])
