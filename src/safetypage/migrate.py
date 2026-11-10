"""Numbered plain-SQL migrations, tracked in ``PRAGMA user_version``. No ORM.

Two schemas ship with the package: ``corpus`` (documents and text) and ``ops`` (runs, traces, the
call log). A file ``NNNN_name.sql`` is applied once, in order, inside a transaction; a failed
migration leaves the database at the previous version.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final, Literal

__all__ = ["Migration", "MigrationError", "current_version", "load_migrations", "migrate"]

Schema = Literal["corpus", "ops"]

_NAME_RE: Final = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(schema: Schema | Traversable) -> list[Migration]:
    """Read a schema's migrations, checking they are numbered 1, 2, 3... without gaps."""
    root = (
        resources.files("safetypage.migrations").joinpath(schema)
        if isinstance(schema, str)
        else schema
    )
    found: list[Migration] = []
    for entry in root.iterdir():
        m = _NAME_RE.fullmatch(entry.name)
        if m is not None:
            found.append(Migration(int(m.group(1)), m.group(2), entry.read_text(encoding="utf-8")))
    found.sort(key=lambda mig: mig.version)
    for expected, mig in enumerate(found, start=1):
        if mig.version != expected:
            raise MigrationError(
                f"migrations must be numbered without gaps: expected {expected:04d}, "
                f"found {mig.version:04d}_{mig.name}"
            )
    return found


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _statements(sql: str) -> list[str]:
    out: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                out.append(buffer)
            buffer = ""
    if buffer.strip():
        raise MigrationError("migration ends with an incomplete SQL statement")
    return out


def migrate(conn: sqlite3.Connection, schema: Schema | Traversable) -> int:
    """Bring ``conn`` up to the newest migration of ``schema``. Returns the version reached."""
    migrations = load_migrations(schema)
    version = current_version(conn)
    if version > len(migrations):
        raise MigrationError(
            f"database is at version {version}, newer than this code knows ({len(migrations)})"
        )
    if conn.in_transaction:
        raise MigrationError("migrate() must be called outside a transaction")
    saved_isolation = conn.isolation_level
    conn.isolation_level = None  # explicit BEGIN/COMMIT, so DDL is transactional too
    try:
        for mig in migrations[version:]:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _statements(mig.sql):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {mig.version:d}")
                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK")
                raise MigrationError(
                    f"migration {mig.version:04d}_{mig.name} failed: {exc}"
                ) from exc
    finally:
        conn.isolation_level = saved_isolation
    return len(migrations)
