"""NEDB test-database lifecycle: HTTP create / drop / recreate.

DYOR (nedb-dyor-2026-10-30.md), section 9, implications 4, 5 and 8 --
work at the execution/semantics layer only (implication 1):

* Databases are never created or dropped via SQL. NEDB has no
  ``postgres`` maintenance database and refuses all DDL by design
  (pgwire.rs:1246-1255); a database must exist before pgwire serves
  it, created over nedbd's HTTP API (``POST /v1/databases``).
* Test teardown is NOT ``DROP DATABASE`` and never ``TRUNCATE``:
  TRUNCATE is refused by design ("NEDB is append-only so that history
  cannot be discarded"), so teardown and flush semantics are
  drop + recreate of the whole database over HTTP
  (``DELETE /v1/databases/:name`` then ``POST /v1/databases``),
  leaving an empty, pre-created test database behind (implication 5).
* The TestCase wrap-in-transaction replacement from implication 4
  starts here: a fresh test database per run is created by
  drop + recreate, never by savepoints or row deletion.

The HTTP endpoint is resolved, in order, from the connection's
``OPTIONS`` (``nedbd_url`` / ``nedbd_http_port`` / ``nedbd_token``),
the ``NEDBD_URL`` / ``NEDBD_HTTP_PORT`` / ``NEDBD_TOKEN`` environment
variables (the official client's env surface, DYOR section 6), or
derived from the pgwire ``HOST`` with the spike's HTTP port 17070.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from django.db.backends.postgresql.creation import (
    DatabaseCreation as PostgresDatabaseCreation,
)

DEFAULT_HTTP_PORT = 17070


class NedbHttpError(RuntimeError):
    """nedbd HTTP API failure; ``status`` is None on transport errors."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class DatabaseCreation(PostgresDatabaseCreation):
    # -- HTTP endpoint resolution -------------------------------------

    def _options(self):
        return self.connection.settings_dict.get("OPTIONS") or {}

    def http_base_url(self):
        options = self._options()
        url = (
            options.get("nedbd_url")
            or options.get("NEDBD_URL")
            or os.environ.get("NEDBD_URL")
        )
        if url:
            return url.rstrip("/")
        host = self.connection.settings_dict.get("HOST") or "127.0.0.1"
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/", 1)[0].split(":", 1)[0] or "127.0.0.1"
        port = (
            options.get("nedbd_http_port")
            or os.environ.get("NEDBD_HTTP_PORT")
            or DEFAULT_HTTP_PORT
        )
        return "http://%s:%s" % (host, port)

    def _http_token(self):
        return (
            self._options().get("nedbd_token")
            or os.environ.get("NEDBD_TOKEN")
            or ""
        )

    # -- HTTP transport (one method; tests mock this seam) ------------

    def _http_request(self, method, path, payload=None):
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        token = self._http_token()
        if token:
            headers["Authorization"] = "Bearer %s" % token
        request = urllib.request.Request(
            self.http_base_url() + path, data=body, headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise NedbHttpError(
                "nedbd %s %s -> HTTP %s: %s" % (method, path, exc.code, detail),
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise NedbHttpError(
                "nedbd %s %s unreachable: %s" % (method, path, exc.reason)
            ) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- database primitives over HTTP (DYOR section 4 surface) -------

    def database_exists(self, name):
        payload = self._http_request("GET", "/v1/databases")
        entries = payload.get("databases", []) if isinstance(payload, dict) else []
        names = {
            entry.get("name") if isinstance(entry, dict) else entry
            for entry in entries
        }
        return name in names

    def create_database(self, name):
        """POST /v1/databases. Returns True if this call created it."""
        try:
            self._http_request("POST", "/v1/databases", {"name": name})
        except NedbHttpError as exc:
            if exc.status == 409:  # already exists: creation is idempotent
                return False
            raise
        return True

    def ensure_database(self, name):
        """Create iff missing (the official client's ensure semantics)."""
        if self.database_exists(name):
            return False
        return self.create_database(name)

    def drop_database(self, name):
        """DELETE /v1/databases/:name. A missing database is success.

        Measured on nedbd-v2 12.15.16: after a drop, a recreate POST
        returns an empty database (no collections, no readable rows)
        whose seq/head continue the dropped incarnation's chain --
        the append-only provenance clock is never rewound, which is
        DYOR section 1 behaviour, not leftover data.
        """
        self.connection.close()
        try:
            self._http_request(
                "DELETE", "/v1/databases/%s" % urllib.parse.quote(name, safe="")
            )
        except NedbHttpError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def reset_database(self, name):
        """Flush by drop + recreate over HTTP -- never TRUNCATE (9.5)."""
        self.drop_database(name)
        self.create_database(name)
        return name

    # The flush/teardown primitive under its Django-facing name.
    flush_database = reset_database

    # -- Django test-database hooks: no SQL, HTTP only -----------------

    def _execute_create_test_db(self, cursor, parameters, keepdb=False):
        # The cursor is never touched: CREATE DATABASE is refused by
        # NEDB, so creation goes over HTTP regardless of the caller.
        name = str(parameters["dbname"]).strip('"')
        if keepdb:
            self.ensure_database(name)
        else:
            self.create_database(name)

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        # No maintenance-database cursor (NEDB has none). keepdb keeps
        # an existing test database; otherwise the test database is
        # reset by drop + recreate so every run starts empty -- the
        # prompt/autoclobber SQL flow has no NEDB equivalent.
        test_database_name = self._get_test_db_name()
        try:
            if keepdb:
                self.ensure_database(test_database_name)
            else:
                self.reset_database(test_database_name)
        except NedbHttpError as exc:
            self.log("Got an error creating the test database: %s" % exc)
            sys.exit(2)
        return test_database_name

    def _destroy_test_db(self, test_database_name, verbosity):
        # Teardown = drop + recreate over HTTP (DYOR 9.5): the data is
        # gone, an empty pre-created database remains for the next run,
        # and no DROP DATABASE / TRUNCATE SQL is ever emitted. A failed
        # teardown is logged, never allowed to mask the suite's result.
        self.connection.close()
        try:
            self.reset_database(test_database_name)
        except NedbHttpError as exc:
            self.log(
                "NEDB backend: test database teardown over HTTP failed "
                "for %s: %s" % (test_database_name, exc)
            )
        return test_database_name

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        # No CREATE DATABASE ... TEMPLATE (DDL, refused) and no COPY
        # (refused by design, DYOR section 5): a clone is a fresh empty
        # database over HTTP; collections are created implicitly by
        # the first write, so a schema-only clone is the NEDB shape.
        target = self.get_test_db_clone_settings(suffix)["NAME"]
        if keepdb:
            self.ensure_database(target)
        else:
            self.reset_database(target)
