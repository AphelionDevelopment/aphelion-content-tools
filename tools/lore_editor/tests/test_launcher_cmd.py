from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


LAUNCHER_CMD_PATH = Path(__file__).resolve().parents[3] / "Launch Lore Tools.cmd"


class LauncherCmdArgumentQuotingTests(unittest.TestCase):
	"""Regression coverage for the launcher batch file's own argument quoting.

	`%~dp0` always expands with a trailing backslash. Quoting it bare as `"%~dp0"` hits a classic
	Windows argument-parsing hazard: a backslash immediately before a closing quote escapes the quote
	into a literal character instead of ending the string, so PowerShell receives a path with a
	stray trailing `"` and Resolve-Path fails with "Illegal characters in path". This is exercised
	against real cmd.exe, with a stub launch.ps1 standing in for the real one so the test does not
	need to start an actual server.
	"""

	def test_launcher_does_not_quote_a_bare_trailing_backslash(self) -> None:
		launcher_text = LAUNCHER_CMD_PATH.read_text(encoding="utf-8")

		self.assertNotIn('-RepositoryRoot "%~dp0"', launcher_text)

	def test_repository_root_argument_survives_cmd_exe_quoting(self) -> None:
		launcher_text = LAUNCHER_CMD_PATH.read_text(encoding="utf-8")

		with tempfile.TemporaryDirectory() as temp_dir:
			temp_root = Path(temp_dir)
			(temp_root / "tools" / "launcher").mkdir(parents=True)
			(temp_root / "tools" / "launcher" / "launch.ps1").write_text(
				"param([Parameter(Mandatory=$true)][string]$RepositoryRoot)\n"
				"$resolved = (Resolve-Path -LiteralPath $RepositoryRoot).Path\n"
				"Write-Output \"RESOLVED=$resolved\"\n",
				encoding="utf-8",
			)
			batch_path = temp_root / "Launch Lore Tools.cmd"
			batch_path.write_text(launcher_text, encoding="utf-8")

			result = subprocess.run(
				["cmd.exe", "/c", "call", str(batch_path)],
				cwd=temp_root,
				capture_output=True,
				text=True,
				timeout=20,
			)

		combined_output = result.stdout + result.stderr
		self.assertNotIn("Illegal characters in path", combined_output)
		self.assertIn(f"RESOLVED={temp_root}", combined_output)


if __name__ == "__main__":
	unittest.main()
