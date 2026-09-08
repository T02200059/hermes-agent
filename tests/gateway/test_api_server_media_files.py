"""API-server MEDIA file registration + download (non-image attachments)."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import pytest

pytest.importorskip("aiohttp")

from gateway.platforms.api_server_media import (
    ApiMediaStore,
    attach_hermes_files,
    finalize_api_media,
    guess_media_mime,
)


class TestApiMediaStore(unittest.TestCase):
    def _write(self, suffix: str, body: bytes = b"hello report") -> Path:
        d = Path(tempfile.mkdtemp(prefix="hermes_api_media_"))
        p = d / f"inspect-report{suffix}"
        p.write_bytes(body)
        return p

    def test_register_md_strips_path_from_public_dict(self):
        p = self._write(".md", b"# report\n")
        store = ApiMediaStore()
        public = store.register(str(p), session_id="sess-1")
        self.assertIsNotNone(public)
        assert public is not None
        self.assertTrue(public["id"].startswith("med_"))
        self.assertEqual(public["name"], p.name)
        self.assertIn("markdown", public["mime"])
        self.assertEqual(public["size"], p.stat().st_size)
        self.assertEqual(public["download"], f"/v1/media/{public['id']}")
        self.assertNotIn("path", public)
        self.assertNotIn(str(p), str(public))

    def test_get_roundtrip(self):
        p = self._write(".pdf", b"%PDF-fake")
        store = ApiMediaStore()
        public = store.register(str(p))
        rec = store.get(public["id"])
        self.assertIsNotNone(rec)
        self.assertEqual(rec.path, str(p.resolve()))

    def test_unknown_id_is_none(self):
        store = ApiMediaStore()
        self.assertIsNone(store.get("med_notreal12ab"))
        self.assertIsNone(store.get("../etc/passwd"))
        self.assertIsNone(store.get("med_"))

    def test_denied_path_not_registered(self):
        store = ApiMediaStore()
        self.assertIsNone(store.register("/etc/passwd"))

    def test_ttl_expiry(self):
        p = self._write(".txt")
        store = ApiMediaStore(ttl_seconds=0.05)
        public = store.register(str(p))
        self.assertIsNotNone(store.get(public["id"]))
        time.sleep(0.08)
        self.assertIsNone(store.get(public["id"]))

    def test_guess_mime(self):
        self.assertIn("markdown", guess_media_mime("/tmp/a.md"))
        self.assertEqual(guess_media_mime("/tmp/a.pdf"), "application/pdf")


class TestFinalizeApiMedia(unittest.TestCase):
    def test_md_tag_registered_and_stripped(self):
        d = Path(tempfile.mkdtemp(prefix="hermes_api_media_"))
        p = d / "gpu-inspect-report.md"
        p.write_text("# cluster\n", encoding="utf-8")
        store = ApiMediaStore()
        text = f"摘要如下。\n\nMEDIA:{p}\n"
        cleaned, files = finalize_api_media(text, store, session_id="web-1")
        self.assertNotIn("MEDIA:", cleaned)
        self.assertNotIn(str(p), cleaned)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "gpu-inspect-report.md")
        self.assertTrue(files[0]["download"].startswith("/v1/media/med_"))

    def test_attach_hermes_files(self):
        payload: dict = {"choices": []}
        attach_hermes_files(payload, [{"id": "med_abc"}])
        self.assertEqual(payload["hermes"]["files"][0]["id"], "med_abc")
        empty: dict = {}
        attach_hermes_files(empty, [])
        self.assertNotIn("hermes", empty)


if __name__ == "__main__":
    unittest.main()
