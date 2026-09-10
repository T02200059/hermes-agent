"""API-server MEDIA file ingestion + download (non-image attachments)."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("aiohttp")

from gateway.platforms.api_server_media import (
    ApiMediaStore,
    attach_hermes_files,
    finalize_api_media,
    guess_media_mime,
)


class _StoreCase(unittest.TestCase):
    """Shared fixture: a temp root so tests never touch the real store."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="hermes_api_media_"))
        self.root = self._tmp / "store"

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _store(self, **kwargs) -> ApiMediaStore:
        kwargs.setdefault("root", self.root)
        return ApiMediaStore(**kwargs)

    def _write(self, name: str, body: bytes = b"hello report") -> Path:
        d = self._tmp / "produced"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_bytes(body)
        return p

    def _blob(self, store: ApiMediaStore, media_id: str) -> Path:
        matches = list(store.root.glob(f"{media_id}__*"))
        self.assertEqual(len(matches), 1, f"expected exactly one blob for {media_id}")
        return matches[0]


class TestApiMediaStore(_StoreCase):
    def test_register_ingests_bytes_and_hides_store_path(self):
        p = self._write("inspect-report.md", b"# report\n")
        store = self._store()
        public = store.register(str(p), session_id="sess-1")

        self.assertIsNotNone(public)
        assert public is not None
        self.assertTrue(public["id"].startswith("med_"))
        self.assertEqual(public["name"], "inspect-report.md")
        self.assertIn("markdown", public["mime"])
        self.assertEqual(public["size"], p.stat().st_size)
        self.assertEqual(public["download"], f"/v1/media/{public['id']}")
        self.assertNotIn("path", public)
        self.assertNotIn(str(p), str(public))

        blob = self._blob(store, public["id"])
        self.assertEqual(blob.read_bytes(), b"# report\n")
        self.assertEqual(blob.name, f"{public['id']}__inspect-report.md")
        self.assertTrue(str(blob).startswith(str(self.root)))

    def test_get_roundtrip(self):
        p = self._write("inspect-report.pdf", b"%PDF-fake")
        store = self._store()
        public = store.register(str(p))
        rec = store.get(public["id"])
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(Path(rec.path).is_file())
        self.assertEqual(rec.name, "inspect-report.pdf")
        self.assertEqual(Path(rec.path).read_bytes(), b"%PDF-fake")

    def test_store_survives_process_restart(self):
        """The directory is the index: a fresh store on the same root still resolves."""
        p = self._write("inspect-report.md", b"# report\n")
        first = self._store()
        public = first.register(str(p))
        del first

        reopened = self._store()
        rec = reopened.get(public["id"])
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(Path(rec.path).read_bytes(), b"# report\n")
        self.assertEqual(rec.name, "inspect-report.md")

    def test_download_survives_source_removal(self):
        """The store owns the bytes — the producer's file is not load-bearing."""
        p = self._write("inspect-report.md", b"# report\n")
        store = self._store()
        public = store.register(str(p))
        p.unlink()
        rec = store.get(public["id"])
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(Path(rec.path).is_file())

    def test_unknown_id_is_none(self):
        store = self._store()
        self.assertIsNone(store.get("med_notreal12ab"))
        self.assertIsNone(store.get("../etc/passwd"))
        self.assertIsNone(store.get("med_"))
        self.assertIsNone(store.get("med_../../etc/passwd"))

    def test_denied_path_not_registered(self):
        store = self._store()
        self.assertIsNone(store.register("/etc/passwd"))
        self.assertEqual(list(store.root.iterdir()), [])

    def test_oversized_file_rejected(self):
        p = self._write("big.md", b"0123456789")
        store = self._store(max_bytes=4)
        self.assertIsNone(store.register(str(p)))
        self.assertEqual(list(store.root.iterdir()), [])

    def test_ttl_expiry(self):
        p = self._write("report.txt")
        store = self._store(ttl_seconds=0.05)
        public = store.register(str(p))
        self.assertIsNotNone(store.get(public["id"]))
        time.sleep(0.08)
        self.assertIsNone(store.get(public["id"]))

    def test_expiry_is_measured_from_registration_not_source_mtime(self):
        """An old source file must not be born already expired."""
        p = self._write("old-report.md")
        os.utime(p, (1000.0, 1000.0))
        store = self._store(ttl_seconds=3600)
        public = store.register(str(p))
        self.assertIsNotNone(store.get(public["id"]))

    def test_sweep_removes_expired_entries(self):
        p = self._write("report.md")
        store = self._store(ttl_seconds=10)
        public = store.register(str(p))
        blob = self._blob(store, public["id"])
        os.utime(blob, (1000.0, 1000.0))
        self.assertEqual(store.sweep(now=1100.0), 1)
        self.assertFalse(blob.exists())

    def test_sweep_evicts_oldest_past_entry_cap(self):
        store = self._store(max_entries=2)
        ids = []
        for i in range(5):
            pub = store.register(str(self._write(f"report-{i}.md")))
            ids.append(pub["id"])
            os.utime(self._blob(store, pub["id"]), (1000.0 + i, 1000.0 + i))
        store.sweep(now=1000.0 + 10)
        survivors = sorted(p.name for p in store.root.iterdir())
        self.assertEqual(len(survivors), 2)
        self.assertTrue(survivors[0].startswith(ids[3]))
        self.assertTrue(survivors[1].startswith(ids[4]))

    def test_sweep_leaves_foreign_files_alone(self):
        """Only files this store minted are ever candidates for deletion."""
        store = self._store()
        store.register(str(self._write("report.md")))
        keepers = [store.root / "notes.txt", store.root / "README"]
        for k in keepers:
            k.write_text("not ours")
        store.sweep(now=time.time() + 10 ** 9)
        for k in keepers:
            self.assertTrue(k.exists(), f"{k.name} must survive the sweep")

    def test_sweep_drops_stale_staging_files(self):
        store = self._store()
        stale = store.root / "med_abcdefgh1234__report.md.part"
        stale.write_bytes(b"half")
        os.utime(stale, (1000.0, 1000.0))
        self.assertEqual(store.sweep(now=1000.0 + 7200), 1)
        self.assertFalse(stale.exists())

    def test_filename_is_sanitized(self):
        p = self._write('we "ird\nname.md', b"x")
        store = self._store()
        public = store.register(str(p))
        self.assertNotIn('"', public["name"])
        self.assertNotIn("\n", public["name"])
        rec = store.get(public["id"])
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(Path(rec.path).is_file())

    def test_guess_mime(self):
        self.assertIn("markdown", guess_media_mime("/tmp/a.md"))
        self.assertEqual(guess_media_mime("/tmp/a.pdf"), "application/pdf")


class TestStoreConfig(_StoreCase):
    def test_env_dir_wins_over_config(self):
        with mock.patch(
            "gateway.platforms.api_server_media._load_media_store_config",
            return_value={"dir": str(self._tmp / "from-config")},
        ):
            with mock.patch.dict(
                os.environ, {"HERMES_API_MEDIA_STORE_DIR": str(self._tmp / "from-env")}
            ):
                store = ApiMediaStore.from_config()
        self.assertEqual(store.root, self._tmp / "from-env")

    def test_config_dir_used_when_env_absent(self):
        with mock.patch(
            "gateway.platforms.api_server_media._load_media_store_config",
            return_value={"dir": str(self._tmp / "from-config"), "ttl_hours": 1},
        ):
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HERMES_API_MEDIA_STORE_DIR", None)
                os.environ.pop("HERMES_API_MEDIA_STORE_TTL_HOURS", None)
                store = ApiMediaStore.from_config()
        self.assertEqual(store.root, self._tmp / "from-config")

    def test_defaults_when_no_config(self):
        from gateway.platforms.api_server_media import default_store_dir

        expected_suffix = os.path.join("cache", "documents", "api-media")
        self.assertTrue(str(default_store_dir()).endswith(expected_suffix))

        fallback = self._tmp / "cache" / "documents" / "api-media"
        with mock.patch(
            "gateway.platforms.api_server_media._load_media_store_config",
            return_value={},
        ):
            with mock.patch(
                "gateway.platforms.api_server_media.default_store_dir",
                return_value=fallback,
            ):
                os.environ.pop("HERMES_API_MEDIA_STORE_DIR", None)
                store = ApiMediaStore.from_config()
        self.assertEqual(store.root, fallback)

    def test_malformed_values_fall_back_to_defaults(self):
        with mock.patch(
            "gateway.platforms.api_server_media._load_media_store_config",
            return_value={"ttl_hours": "not-a-number", "max_entries": -5},
        ):
            os.environ.pop("HERMES_API_MEDIA_STORE_DIR", None)
            store = ApiMediaStore.from_config()
        self.assertEqual(store._ttl, 720 * 3600)
        self.assertEqual(store._max_entries, 4096)


class TestFinalizeApiMedia(_StoreCase):
    def test_md_tag_registered_and_stripped(self):
        p = self._write("gpu-inspect-report.md", b"# cluster\n")
        store = self._store()
        text = f"摘要如下。\n\nMEDIA:{p}\n"
        cleaned, files = finalize_api_media(text, store, session_id="web-1")
        self.assertNotIn("MEDIA:", cleaned)
        self.assertNotIn(str(p), cleaned)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "gpu-inspect-report.md")
        self.assertTrue(files[0]["download"].startswith("/v1/media/med_"))
        rec = store.get(files[0]["id"])
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertTrue(Path(rec.path).is_file())

    def test_attach_hermes_files(self):
        payload: dict = {"choices": []}
        attach_hermes_files(payload, [{"id": "med_abc"}])
        self.assertEqual(payload["hermes"]["files"][0]["id"], "med_abc")
        empty: dict = {}
        attach_hermes_files(empty, [])
        self.assertNotIn("hermes", empty)


if __name__ == "__main__":
    unittest.main()
