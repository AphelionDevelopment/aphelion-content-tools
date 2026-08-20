from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from webapp.game_repository import validate_game_repository


class GameRepositoryValidationTests(unittest.TestCase):
	def test_accepts_checkout_with_matching_remote(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			subprocess.run(["git", "-C", str(game_root), "init", "--initial-branch=main"], check=True, capture_output=True, text=True)
			subprocess.run(
				["git", "-C", str(game_root), "remote", "add", "origin", "https://example.invalid/Meridian-Rift.git"],
				check=True, capture_output=True, text=True,
			)

			validate_game_repository(game_root)  # does not raise

	def test_rejects_missing_directory(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			missing_root = Path(temp_dir) / "does-not-exist"

			with self.assertRaisesRegex(ValueError, "does not exist"):
				validate_game_repository(missing_root)

	def test_rejects_checkout_missing_marker_file(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)

			with self.assertRaisesRegex(ValueError, "does not look like a Meridian-Rift checkout"):
				validate_game_repository(game_root)

	def test_rejects_checkout_with_mismatched_remote(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")
			subprocess.run(["git", "-C", str(game_root), "init", "--initial-branch=main"], check=True, capture_output=True, text=True)
			subprocess.run(
				["git", "-C", str(game_root), "remote", "add", "origin", "https://example.invalid/some-other-fork.git"],
				check=True, capture_output=True, text=True,
			)

			with self.assertRaisesRegex(ValueError, "does not look like Meridian-Rift"):
				validate_game_repository(game_root)

	def test_accepts_checkout_with_no_git_remote_configured(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			game_root = Path(temp_dir)
			(game_root / "tgstation.dme").write_text("", encoding="utf-8")

			validate_game_repository(game_root)  # does not raise


if __name__ == "__main__":
	unittest.main()
