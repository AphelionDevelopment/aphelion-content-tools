from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


def write_json(path: Path, payload: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class CliTests(unittest.TestCase):
	def make_repo(self, *, valid_entry: bool = True) -> Path:
		temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(temp_dir.cleanup)
		repo_root = Path(temp_dir.name)
		write_json(
			repo_root / "config/aphelion/lore_overhaul/targets.json",
			[
				{
					"type_path": "/obj/item/radio",
					"label": "Handheld Radio",
					"editable_root": "/obj/item/radio",
					"parent_type": "/obj/item",
					"field_profile": "atom_like",
					"base_values": {"name": "radio", "description": "A radio."},
					"icon_metadata": {},
				}
			],
		)
		entry = {
			"id": "fixture.radio",
			"type_path": "/obj/item/radio" if valid_entry else "/obj/item/unknown",
			"name": "fixture radio",
		}
		write_json(repo_root / "config/aphelion/lore_overhaul/entities/items.json", [entry])
		return repo_root

	def run_cli(self, *arguments: str) -> tuple[int, str, str]:
		from tools.lore_editor import cli

		stdout = StringIO()
		stderr = StringIO()
		with redirect_stdout(stdout), redirect_stderr(stderr):
			status = cli.main(list(arguments))
		return status, stdout.getvalue(), stderr.getvalue()

	def test_validate_returns_zero_for_valid_matching_generated_output(self) -> None:
		from tools.lore_editor.generate import write_generated_dm

		repo_root = self.make_repo()
		write_generated_dm(repo_root)

		status, stdout, stderr = self.run_cli(
			"validate",
			"--repo-root",
			str(repo_root),
			"--check-generated",
		)

		self.assertEqual(status, 0)
		self.assertIn("valid", stdout.lower())
		self.assertEqual(stderr, "")

	def test_validate_returns_nonzero_without_writing_invalid_repository(self) -> None:
		from tools.lore_editor.generate import write_generated_dm

		repo_root = self.make_repo()
		write_generated_dm(repo_root)
		generated_path = repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm"
		before = generated_path.read_bytes()
		write_json(
			repo_root / "config/aphelion/lore_overhaul/entities/items.json",
			[
				{
					"id": "fixture.radio",
					"type_path": "/obj/item/unknown",
					"name": "invalid fixture",
				}
			],
		)

		status, stdout, stderr = self.run_cli(
			"validate",
			"--repo-root",
			str(repo_root),
			"--check-generated",
		)

		self.assertNotEqual(status, 0)
		self.assertIn("fixture.radio", stdout + stderr)
		self.assertEqual(generated_path.read_bytes(), before)

	def test_generate_dispatch_writes_generated_artifact(self) -> None:
		repo_root = self.make_repo()

		status, stdout, stderr = self.run_cli("generate", "--repo-root", str(repo_root))

		self.assertEqual(status, 0)
		self.assertIn("generated", stdout.lower())
		self.assertEqual(stderr, "")
		self.assertTrue(
			(repo_root / "modular_aphelion/modules/lore_overhaul/code/generated_lore_overrides.dm").exists()
		)

	def test_catalog_refresh_dispatches_and_reports_errors(self) -> None:
		repo_root = self.make_repo()
		with patch("tools.lore_editor.cli.refresh_catalog", return_value=[{"type_path": "/obj/item/radio"}]) as refresh:
			status, stdout, stderr = self.run_cli("catalog-refresh", "--repo-root", str(repo_root))

		refresh.assert_called_once_with(repo_root.resolve())
		self.assertEqual(status, 0)
		self.assertIn("catalog", stdout.lower())
		self.assertEqual(stderr, "")

	def test_catalog_refresh_reports_changed_and_stale_targets(self) -> None:
		repo_root = self.make_repo()
		probe_output_path = repo_root / "data/lore_overhaul_targets.json"
		write_json(probe_output_path, [
			{
				"type_path": "/obj/item/radio",
				"label": "Handheld Radio",
				"editable_root": "/obj/item",
				"parent_type": "/obj/item",
				"field_profile": "atom_like",
				"base_values": {"name": "radio", "description": "An updated radio."},
				"icon_metadata": {},
			}
		])

		with patch("tools.lore_editor.catalog._run_catalog_probe", return_value=probe_output_path):
			status, stdout, stderr = self.run_cli("catalog-refresh", "--repo-root", str(repo_root))

		self.assertEqual(status, 0, stderr)
		self.assertIn("Changed in the game repository (1)", stdout)
		self.assertIn("/obj/item/radio", stdout)
		self.assertIn("Overrides affected by these changes (1)", stdout)

	def test_direct_script_entrypoint_supports_repository_command(self) -> None:
		repo_root = self.make_repo()
		cli_path = Path(__file__).resolve().parents[1] / "cli.py"
		result = subprocess.run(
			[
				sys.executable,
				str(cli_path),
				"validate",
				"--repo-root",
				str(repo_root),
			],
			cwd=Path(__file__).resolve().parents[3],
			capture_output=True,
			text=True,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("valid", result.stdout.lower())

	def test_prepare_export_dispatches_to_staging_service(self) -> None:
		from tools.lore_editor import cli
		from tools.lore_editor.export import PreparedExport

		repo_root = self.make_repo()
		game_root = self.make_repo()
		prepared = PreparedExport(Path("stage"), Path("artifact"), object())
		with patch.object(cli, "prepare_export", return_value=prepared) as prepare:
			status, stdout, stderr = self.run_cli(
				"prepare-export",
				"--repo-root",
				str(repo_root),
				"--game-repo",
				str(game_root),
			)

		prepare.assert_called_once_with(repo_root.resolve(), game_root.resolve(), repo_root.resolve() / "tools/lore_editor/stages")
		self.assertEqual(status, 0)
		self.assertIn("stage", stdout.lower())
		self.assertEqual(stderr, "")

	def test_apply_export_dispatches_to_application_service(self) -> None:
		repo_root = self.make_repo()
		game_root = self.make_repo()
		with patch("tools.lore_editor.cli.apply_export", return_value=game_root / "artifact") as apply:
			status, stdout, stderr = self.run_cli(
				"apply-export",
				"--stage",
				"stage",
				"--game-repo",
				str(game_root),
			)

		apply.assert_called_once_with(Path("stage"), game_root.resolve())
		self.assertEqual(status, 0)
		self.assertIn("applied", stdout.lower())
		self.assertEqual(stderr, "")


if __name__ == "__main__":
	unittest.main()
