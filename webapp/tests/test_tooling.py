from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from webapp.tooling import ToolDefinition, build_tool_command, get_tool_run, list_tools, start_tool


GENERATE_DEFINITION = ToolDefinition(
	id="generate",
	label="Generate DM",
	description="Regenerate the checked-in lore override DM artifact.",
	tool_root="tools/lore_editor",
	commands=(("generate",),),
)
VALIDATE_DEFINITION = ToolDefinition(
	id="validate",
	label="Validate content",
	description="Validate lore JSON and check the generated DM artifact.",
	tool_root="tools/lore_editor",
	commands=(("validate", "--check-generated"),),
	game_repo_commands=frozenset({"validate"}),
)
TEST_DEFINITIONS = (GENERATE_DEFINITION, VALIDATE_DEFINITION)


class ToolingTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repo_root = Path(self.temp_dir.name)
		(self.repo_root / "config/aphelion/lore_overhaul/entities").mkdir(parents=True)
		(self.repo_root / "config/aphelion/lore_overhaul/entities/.gitkeep").write_text("", encoding="utf-8")
		(self.repo_root / "config/aphelion/lore_overhaul/targets.json").write_text("[]\n", encoding="utf-8")
		cli_path = self.repo_root / "tools/lore_editor/cli.py"
		cli_path.parent.mkdir(parents=True)
		cli_path.write_text("print('Generated lore DM artifact.')\n", encoding="utf-8")

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def test_allowlist_exposes_named_tools_and_fixed_commands(self) -> None:
		tools = list_tools(TEST_DEFINITIONS)
		self.assertEqual({tool["id"] for tool in tools}, {"generate", "validate"})
		command = build_tool_command(self.repo_root, VALIDATE_DEFINITION)
		self.assertEqual(command[0], __import__("sys").executable)
		self.assertIn("tools/lore_editor/cli.py", command[1].replace("\\", "/"))
		self.assertIn("--check-generated", command)
		with self.assertRaises(ValueError):
			build_tool_command(self.repo_root, VALIDATE_DEFINITION, command_index=5)

	def test_generate_tool_runs_to_completion_and_captures_output(self) -> None:
		run = start_tool(self.repo_root, TEST_DEFINITIONS, "generate")
		self.assertIn(run["status"], {"queued", "running"})
		deadline = time.monotonic() + 10
		while time.monotonic() < deadline:
			current = get_tool_run(run["run_id"])
			if current["status"] not in {"queued", "running"}:
				break
			time.sleep(0.05)
		else:
			self.fail("Tool run did not finish before the test deadline.")
		self.assertEqual(current["status"], "succeeded")
		self.assertIn("Generated lore DM artifact", current["output"])
		self.assertIsInstance(current["log_path"], str)
		log_path = self.repo_root / current["log_path"]
		self.assertTrue(log_path.is_file())
		self.assertIn("Generated lore DM artifact", log_path.read_text(encoding="utf-8"))

	def test_unknown_tool_and_unknown_run_are_rejected(self) -> None:
		with self.assertRaises(ValueError):
			start_tool(self.repo_root, TEST_DEFINITIONS, "arbitrary-command")
		with self.assertRaises(ValueError):
			get_tool_run("missing-run")


if __name__ == "__main__":
	unittest.main()
