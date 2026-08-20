from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.dmi import Dmi


def write_dmi(path: Path, *states: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	dmi = Dmi(32, 32)
	for state_name in states:
		state = dmi.state(state_name)
		state.frame(Image.new("RGBA", (32, 32), (255, 0, 0, 255)))
	dmi.to_file(path)


class IconPreviewTests(unittest.TestCase):
	def test_preview_renders_first_frame_from_module_icon(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "modular_aphelion/modules/lore_overhaul/icons/fixture.dmi"
			write_dmi(icon_path, "radio")

			png_bytes = render_icon_preview(
				repo_root,
				"modular_aphelion/modules/lore_overhaul/icons/fixture.dmi",
				"radio",
			)

			image = Image.open(io.BytesIO(png_bytes))
			self.assertEqual(image.size, (32, 32))
			self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

	def test_preview_renders_core_icon_assets(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "icons/fixture.dmi"
			write_dmi(icon_path, "radio")

			png_bytes = render_icon_preview(repo_root, "icons/fixture.dmi", "radio")
			image = Image.open(io.BytesIO(png_bytes))
			self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

	def test_preview_renders_nova_module_icon_assets(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "modular_nova/modules/aesthetics/intercom/icons/fixture.dmi"
			write_dmi(icon_path, "intercom")

			png_bytes = render_icon_preview(
				repo_root,
				"modular_nova/modules/aesthetics/intercom/icons/fixture.dmi",
				"intercom",
			)

			image = Image.open(io.BytesIO(png_bytes))
			self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

	def test_preview_renders_nova_master_file_icon_assets(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "modular_nova/master_files/icons/obj/clothing/neck.dmi"
			write_dmi(icon_path, "cape_admiral")

			png_bytes = render_icon_preview(
				repo_root,
				"modular_nova/master_files/icons/obj/clothing/neck.dmi",
				"cape_admiral",
			)

			image = Image.open(io.BytesIO(png_bytes))
			self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

	def test_preview_rejects_assets_outside_approved_icon_roots(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "tools/fixture.dmi"
			write_dmi(icon_path, "radio")

			with self.assertRaises(ValueError):
				render_icon_preview(repo_root, "tools/fixture.dmi", "radio")

	def test_preview_reports_missing_state(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "modular_aphelion/modules/lore_overhaul/icons/fixture.dmi"
			write_dmi(icon_path, "radio")

			with self.assertRaises(ValueError):
				render_icon_preview(
					repo_root,
					"modular_aphelion/modules/lore_overhaul/icons/fixture.dmi",
					"missing",
				)

	def test_preview_uses_an_unnamed_state_as_the_default_when_requested_state_is_missing(self) -> None:
		from tools.lore_editor.icon_preview import render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "icons/default.dmi"
			write_dmi(icon_path, "")

			png_bytes = render_icon_preview(repo_root, "icons/default.dmi", "/obj/item/example")

			image = Image.open(io.BytesIO(png_bytes))
			self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

	def test_preview_does_not_fallback_when_named_states_also_exist(self) -> None:
		from tools.lore_editor.icon_preview import IconPreviewNotFound, render_icon_preview

		with tempfile.TemporaryDirectory() as temp_dir:
			repo_root = Path(temp_dir)
			icon_path = repo_root / "icons/mixed.dmi"
			write_dmi(icon_path, "", "named")

			with self.assertRaises(IconPreviewNotFound):
				render_icon_preview(repo_root, "icons/mixed.dmi", "missing")


if __name__ == "__main__":
	unittest.main()
