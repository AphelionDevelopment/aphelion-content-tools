from __future__ import annotations

import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


class WebLaunchTests(unittest.TestCase):
	def test_editor_assets_are_relative_to_the_page(self) -> None:
		html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

		self.assertIn('href="styles.css"', html)
		self.assertIn('href="favicon.svg"', html)
		self.assertIn('src="app.js"', html)
		self.assertNotIn('href="/styles.css"', html)
		self.assertNotIn('src="/app.js"', html)

	def test_file_launch_explains_that_the_server_is_required(self) -> None:
		javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

		self.assertIn("window.location.protocol === 'file:'", javascript)
		self.assertIn("This editor must be launched through the repository server", javascript)

	def test_editor_search_uses_the_catalog_review_feed(self) -> None:
		html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
		javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

		self.assertIn('id="entry-mode"', html)
		self.assertIn("'/api/review'", javascript)

	def test_editor_has_review_filters_and_writer_actions(self) -> None:
		html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
		javascript = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

		for element_id in (
			"review-tab",
			"config-tab",
			"review-panel",
			"configuration-panel",
			"reviewer-name",
			"review-notes",
			"mark-reviewed-button",
			"flag-attention-button",
			"clear-review-button",
			"group-filters",
			"create-group-button",
			"config-group-list",
			"new-group-id",
			"status-filters",
			"show-directional",
			"show-redundant",
			"sort-select",
			"create-override-button",
			"override-source",
			"special-desc-editor",
			"entry-special-desc-requirement",
			"entry-special-desc",
			"icon-file-input",
			"icon-base-preview",
			"icon-override-preview",
			"tool-list",
			"tool-log-path",
		):
			self.assertIn(f'id="{element_id}"', html)
		self.assertIn("URLSearchParams", javascript)
		self.assertIn("/api/reviews/", javascript)
		self.assertIn("/api/entity-files", javascript)
		self.assertIn("needs-attention", javascript)
		self.assertIn("include_directional", javascript)
		self.assertIn("/api/icon-files", javascript)
		self.assertIn("/api/icon-states", javascript)
		self.assertIn("/api/groups/", javascript)
		self.assertIn("group_match_reasons", javascript)
		self.assertIn("matched_entry_count", javascript)
		self.assertIn("has_more", javascript)
		self.assertIn("load-more", javascript)
		self.assertIn("iconStates.has", javascript)
		self.assertIn("log_path", javascript)
		self.assertIn("special_desc_requirement", javascript)
		self.assertIn("special_desc", javascript)


if __name__ == "__main__":
	unittest.main()
