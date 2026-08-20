from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVE_PATH = REPO_ROOT / "tools" / "lore_editor" / "serve.py"


class ServerStartupTests(unittest.TestCase):
	def setUp(self) -> None:
		self.process = subprocess.Popen(
			[
				sys.executable,
				str(SERVE_PATH),
				"--repo-root",
				str(REPO_ROOT),
				"--port",
				"0",
			],
			cwd=REPO_ROOT,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
		)
		assert self.process.stdout is not None
		deadline = time.time() + 10
		line = ""
		while time.time() < deadline:
			line = self.process.stdout.readline().strip()
			if line.startswith("LORE_EDITOR_URL="):
				break
			if self.process.poll() is not None:
				break
		if not line.startswith("LORE_EDITOR_URL="):
			self.fail(f"Editor did not announce a URL: {line!r}")
		self.base_url = line.split("=", 1)[1]

	def tearDown(self) -> None:
		if self.process.poll() is None:
			self.process.terminate()
			self.process.wait(timeout=5)
		if self.process.stdout is not None:
			self.process.stdout.close()
		if self.process.stderr is not None:
			self.process.stderr.close()

	def fetch(self, path: str) -> tuple[int, str, str]:
		try:
			with urllib.request.urlopen(self.base_url + path, timeout=5) as response:
				return response.status, response.headers.get_content_type(), response.read().decode("utf-8")
		except urllib.error.HTTPError as exc:
			return exc.code, exc.headers.get_content_type(), exc.read().decode("utf-8")

	def test_health_endpoint(self) -> None:
		status, content_type, body = self.fetch("/api/health")

		self.assertEqual(status, 200)
		self.assertEqual(content_type, "application/json")
		self.assertEqual(json.loads(body), {"ok": True, "service": "lore-editor"})

	def test_root_serves_editor_and_missing_path_is_404(self) -> None:
		status, content_type, body = self.fetch("/")

		self.assertEqual(status, 200)
		self.assertEqual(content_type, "text/html")
		self.assertIn("Lore Overhaul Editor", body)

		missing_status, _missing_type, _missing_body = self.fetch("/missing")
		self.assertEqual(missing_status, 404)

		favicon_status, favicon_type, _favicon_body = self.fetch("/favicon.ico")
		self.assertEqual(favicon_status, 200)
		self.assertEqual(favicon_type, "image/svg+xml")


if __name__ == "__main__":
	unittest.main()
