"""One-command verification of the embedded NEDB store.

    python manage.py verify_embedded_store [--data-dir DIR] [--db-name NAME]

Runs the whole embedded pass in one invocation, in its own
subprocesses so no phase inherits another phase's open store:

1. LEVEL  -- the data dir must be the store *root*: the per-database
   dir ``<root>/<db name>`` is the store (it holds ``MANIFEST``). A
   root that is itself a store, a non-store dir at the db path, or a
   root whose stores live under other names all stop the run -- each
   is the wrong-level shape that makes migrate build a fresh store
   beside the real one and report success against nothing.
2. HOLD   -- refuses, hard stop, while another engine holds the
   store: a flock probe on the store's ``LOCK`` file, a /proc scan
   for a nedbd serving this root, and the engine's own split-brain
   refusal when the pre-check tries to open the store.
3. STATE  -- a pre-existing store with data (seq > 0) but no recorded
   migrations stops the run before migrate: migrate would apply
   everything from scratch, which on a store that should already be
   migrated means the level (or the db name) is wrong.
4. MIGRATE in embedded mode (dead pgwire port: no daemon contact is
   possible), then REOPEN and verify: ``verify()`` on the chain, the
   recorded-migration count, and a read-only app-level read (salon
   count + the checkout daily sales summary).

The result is always three separate lines -- MERGED (the checkout
HEAD this run executed), PULLED (the exact store dir this run
targeted, fresh or pre-existing), VERIFIED (the reopen outcome, or
NOT RUN with the reason). They are never collapsed into one claim,
and a run against a scratch store verifies that store, never any
other.
"""

try:
    import fcntl
except ImportError:  # Windows: the engine's own open refusal still guards
    fcntl = None
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

REPO_ROOT = Path(__file__).resolve().parents[3]

# Opens the store directly (no Django), prints one JSON line, exits --
# process exit is what releases the store lock between phases.
_CORE_SNIPPET = """
import json, sys
from nedb._native import NedbCore
out = {"seq": None, "verify": None, "migrations": None, "error": None}
try:
    core = NedbCore.open(sys.argv[1])
    out["seq"] = core.seq()
    out["verify"] = bool(core.verify())
    try:
        out["migrations"] = len(core.nesql('SELECT "id" FROM "django_migrations"'))
    except Exception:
        out["migrations"] = None
except Exception as exc:
    out["error"] = str(exc)
print("STORE_STATE " + json.dumps(out))
"""

# Read-only app-level read through the embedded Django connection.
_READ_SNIPPET = """
import json
from django.utils import timezone
from saloncore.models import Salon
out = {"salons": Salon.objects.count(), "sales_summary": None}
if out["salons"]:
    from checkout.summary import daily_sales_summary
    s = daily_sales_summary(Salon.objects.order_by("id").first(), timezone.now().date())
    out["sales_summary"] = {"discount_total": str(s.discount_total),
                            "sales_count": s.sales_count}
print("READ_STATE " + json.dumps(out))
"""


def store_level_problem(root, db_name):
    """None if the level is right, else a human-readable stop reason."""
    root = Path(root)
    db_dir = root / db_name
    if (root / "MANIFEST").is_file():
        return (
            f"data-dir level wrong: {root} is itself a store (MANIFEST "
            "at the root). NEDB_DATA_DIR must be the PARENT of the "
            f"per-database dir, i.e. the dir containing '{db_name}/'."
        )
    if db_dir.exists():
        if not (db_dir / "MANIFEST").is_file():
            return (
                f"data-dir level wrong: {db_dir} exists but holds no "
                "MANIFEST, so it is not a store root. The store for "
                f"'{db_name}' lives one level up or down from here."
            )
        return None
    if root.is_dir() and any(root.iterdir()):
        others = sorted(
            p.name for p in root.iterdir() if (p / "MANIFEST").is_file()
        )
        if others:
            return (
                f"data-dir level wrong: no store for '{db_name}' under "
                f"{root}, but store(s) exist there under other names: "
                f"{', '.join(others)}. POSTGRES_DB and the store's "
                "directory name disagree -- migrate would create a "
                "fresh store beside the real one."
            )
        return (
            f"no store for '{db_name}' under {root}, and the root "
            "holds other content but no store. Refusing to guess: if "
            "this is a first install on an empty root, remove the "
            "other content or point NEDB_DATA_DIR at an empty dir."
        )
    return None  # root missing or empty: a fresh store is legitimate


def hold_evidence(root, db_name):
    """None, or why another engine appears to hold the store."""
    db_dir = Path(root) / db_name
    lock = db_dir / "LOCK"
    if fcntl is not None and lock.is_file():
        try:
            with open(lock, "r+b") as fh:
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
                except OSError:
                    pid = lock.read_text(errors="replace").strip()
                    return (
                        f"{lock} is flock-held (holder pid {pid or '?'})"
                        " -- an engine (nedbd or another embedded "
                        "process) has this store open"
                    )
        except OSError:
            pass
    proc = Path("/proc")
    if proc.is_dir():
        root_s, dir_s = str(root), str(db_dir)
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
            except OSError:
                continue
            if b"nedbd" in cmd and (root_s.encode() in cmd or dir_s.encode() in cmd):
                return (
                    f"nedbd process {entry.name} is serving this data "
                    f"dir: {cmd.decode(errors='replace').strip()}"
                )
    return None


class Command(BaseCommand):
    help = "Verify the embedded NEDB store: level, hold, migrate, reopen."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=None,
                            help="NEDB store root (default: NEDB_DATA_DIR env / OPTIONS)")
        parser.add_argument("--db-name", default=None,
                            help="database name (default: settings NAME / POSTGRES_DB)")

    # -- subprocess plumbing ------------------------------------------
    def _env(self, root, db_name):
        env = {
            **os.environ,
            "OPENSALON_NEDB_EMBEDDED": "1",
            "NEDB_DATA_DIR": str(root),
            "POSTGRES_DB": db_name,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "59999",  # dead: no daemon may be involved
        }
        env.pop("OPENSALON_USE_SQLITE", None)
        return env

    def _run(self, argv, env, timeout=900, stdin=None):
        return subprocess.run(
            argv, cwd=REPO_ROOT, env=env, input=stdin,
            capture_output=True, text=True, timeout=timeout,
        )

    def _core_state(self, db_dir, env):
        proc = self._run(
            [sys.executable, "-c", _CORE_SNIPPET, str(db_dir)], env, timeout=300
        )
        for line in proc.stdout.splitlines():
            if line.startswith("STORE_STATE "):
                return json.loads(line[len("STORE_STATE "):])
        return {"seq": None, "verify": None, "migrations": None,
                "error": (proc.stdout + proc.stderr)[-500:] or "no state line"}

    # -- reporting ------------------------------------------------------
    def _merged_line(self):
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
        except Exception:
            sha = ""
        return f"MERGED: {sha or 'unknown (not a git checkout)'} (checkout HEAD this run executed)"

    def _report(self, pulled, verified):
        self.stdout.write(self._merged_line())
        self.stdout.write(f"PULLED: {pulled}")
        self.stdout.write(f"VERIFIED: {verified}")

    def _stop(self, pulled, reason):
        self._report(pulled, f"NOT RUN -- {reason}")
        raise CommandError(reason)

    # -- the pass -------------------------------------------------------
    def handle(self, *args, **opts):
        db_name = opts["db_name"] or settings.DATABASES["default"]["NAME"]
        root = opts["data_dir"]
        if not root:
            from opensalon.backends.nedb import embedded

            try:
                root = embedded.data_root(settings.DATABASES["default"])
            except RuntimeError as exc:
                raise CommandError(str(exc))
        root = Path(root).resolve()
        db_dir = root / db_name
        pulled = f"{db_dir} (db '{db_name}')"

        problem = store_level_problem(root, db_name)
        if problem:
            self._stop(pulled, problem)
        fresh = not db_dir.exists()
        if not fresh:
            held = hold_evidence(root, db_name)
            if held:
                self._stop(pulled, f"store is held, refusing to proceed: {held}")

        env = self._env(root, db_name)
        before = None
        if not fresh:
            before = self._core_state(db_dir, env)
            if before["error"]:
                if "locked by another process" in before["error"]:
                    self._stop(pulled, f"store is held, refusing to proceed: {before['error']}")
                self._stop(pulled, f"pre-check could not open the store: {before['error']}")
            if before["seq"] and not before["migrations"]:
                self._stop(
                    pulled,
                    f"store has data (seq {before['seq']}) but no recorded "
                    "migrations -- migrate would apply everything from "
                    "scratch, so the data-dir level (or db name) is "
                    "likely wrong",
                )
            pulled += f" -- PRE-EXISTING store, seq {before['seq']} before migrate"

        mig = self._run([sys.executable, "manage.py", "migrate", "--noinput"], env)
        applied = mig.stdout.count("Applying ")
        if mig.returncode != 0:
            self._report(pulled, "NOT RUN -- migrate failed")
            raise CommandError(
                "migrate failed:\n" + (mig.stdout + mig.stderr)[-2000:]
            )
        if fresh:
            pulled += f" -- FRESH store created by this run ({applied} migrations applied)"

        after = self._core_state(db_dir, env)
        if after["error"]:
            self._stop(pulled, f"reopen failed: {after['error']}")
        if not after["verify"]:
            self._stop(pulled, "reopen: chain verify() returned false")

        read = self._run([sys.executable, "manage.py", "shell"], env,
                          timeout=300, stdin=_READ_SNIPPET)
        state = None
        for line in read.stdout.splitlines():
            if line.startswith("READ_STATE "):
                state = json.loads(line[len("READ_STATE "):])
        if state is None:
            self._stop(pulled, "reopen: app-level read failed:\n"
                               + (read.stdout + read.stderr)[-1000:])
        self._report(
            pulled,
            f"PASS -- chain verify() true, {after['migrations']} migrations "
            f"recorded ({applied} applied by this run), seq {after['seq']}, "
            f"app read ok: {state['salons']} salon(s), sales summary "
            f"{state['sales_summary']}",
        )
