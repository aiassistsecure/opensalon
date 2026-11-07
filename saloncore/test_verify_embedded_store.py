"""Tests for the verify_embedded_store management command.

The check functions (level, hold) are unit-tested with plain tmp
dirs and stand-in holders. The full pass (migrate in embedded mode,
reopen, verify) is gated exactly like the backend acceptance test:
it needs the native core and OPENSALON_NEDB_EMBEDDED_TEST=1, and it
runs against disposable tmp stores only.
"""

import fcntl
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from saloncore.management.commands.verify_embedded_store import (
    hold_evidence,
    store_level_problem,
)


def _mk_store(root, name):
    db_dir = Path(root) / name
    db_dir.mkdir(parents=True)
    (db_dir / "MANIFEST").write_text("{}")
    (db_dir / "LOCK").write_text("")
    (db_dir / "objects").mkdir()
    return db_dir


class LevelCheckTests(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_empty_root_is_fresh_ok(self):
        self.assertIsNone(store_level_problem(self.root, "opensalon"))

    def test_store_at_db_path_is_ok(self):
        _mk_store(self.root, "opensalon")
        self.assertIsNone(store_level_problem(self.root, "opensalon"))

    def test_root_that_is_itself_a_store_is_wrong(self):
        _mk_store(self.root, "inner")
        (Path(self.root) / "MANIFEST").write_text("{}")
        problem = store_level_problem(self.root, "opensalon")
        self.assertIn("level wrong", problem)
        self.assertIn("itself a store", problem)

    def test_non_store_dir_at_db_path_is_wrong(self):
        (Path(self.root) / "opensalon").mkdir()
        problem = store_level_problem(self.root, "opensalon")
        self.assertIn("level wrong", problem)
        self.assertIn("no MANIFEST", problem)

    def test_store_under_another_name_is_wrong(self):
        _mk_store(self.root, "shop")
        problem = store_level_problem(self.root, "opensalon")
        self.assertIn("level wrong", problem)
        self.assertIn("shop", problem)


class HoldCheckTests(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.db_dir = _mk_store(self.root, "opensalon")

    def test_unheld_store_has_no_evidence(self):
        self.assertIsNone(hold_evidence(self.root, "opensalon"))

    def test_flock_held_store_is_evidence(self):
        fh = open(self.db_dir / "LOCK", "r+b")
        self.addCleanup(fh.close)
        fcntl.flock(fh, fcntl.LOCK_EX)
        evidence = hold_evidence(self.root, "opensalon")
        self.assertIn("flock-held", evidence)

    def test_nedbd_process_serving_root_is_evidence(self):
        proc = subprocess.Popen(
            ["bash", "-c",
             f'exec -a "nedbd --data {self.root} --port 17070" sleep 30']
        )
        try:
            evidence = hold_evidence(self.root, "opensalon")
        finally:
            proc.kill()
        self.assertIn("nedbd process", evidence)


def _native_available():
    try:
        from nedb._native import NedbCore  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(_native_available(), "nedb native core not importable")
@unittest.skipUnless(
    os.environ.get("OPENSALON_NEDB_EMBEDDED_TEST") == "1",
    "embedded full pass: set OPENSALON_NEDB_EMBEDDED_TEST=1",
)
class VerifyEmbeddedStoreFlowTests(SimpleTestCase):
    """The whole pass against a disposable store, twice, then held."""

    def _run_cmd(self, root, db_name="verifydb"):
        out = io.StringIO()
        call_command(
            "verify_embedded_store",
            "--data-dir", str(root),
            "--db-name", db_name,
            stdout=out,
        )
        return out.getvalue()

    def test_fresh_reopen_hold_and_wrong_level(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)

        first = self._run_cmd(root)
        self.assertIn("MERGED: ", first)
        self.assertIn("PULLED: ", first)
        self.assertIn("FRESH store created by this run", first)
        self.assertIn("VERIFIED: PASS", first)

        second = self._run_cmd(root)
        self.assertIn("PRE-EXISTING store", second)
        self.assertIn("VERIFIED: PASS", second)
        self.assertIn("(0 applied by this run)", second)

        # Held: an flock on LOCK must stop the run before migrate.
        db_dir = Path(root) / "verifydb"
        manifest = db_dir / "MANIFEST"
        mtime = manifest.stat().st_mtime_ns
        fh = open(db_dir / "LOCK", "r+b")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
            out = io.StringIO()
            with self.assertRaises(CommandError) as ctx:
                call_command(
                    "verify_embedded_store",
                    "--data-dir", str(root),
                    "--db-name", "verifydb",
                    stdout=out,
                )
        finally:
            fh.close()
        self.assertIn("held", str(ctx.exception))
        self.assertIn("VERIFIED: NOT RUN", out.getvalue())
        self.assertEqual(manifest.stat().st_mtime_ns, mtime)

        # Wrong level: the store dir itself passed as the root.
        out = io.StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "verify_embedded_store",
                "--data-dir", str(db_dir),
                "--db-name", "verifydb",
                stdout=out,
            )
        self.assertIn("level wrong", str(ctx.exception))
        self.assertIn("VERIFIED: NOT RUN", out.getvalue())
