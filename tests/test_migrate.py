from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from onthepage.migrate import MigrationError, current_version, load_migrations, migrate

CORPUS_TABLES = {
    "documents",
    "versions",
    "licence_facts",
    "renditions",
    "pages",
    "page_words",
    "blocks",
    "outline",
    "anchor_map",
    "facts",
}
OPS_TABLES = {"runs", "traces", "trace_events", "tool_calls"}


def tables(conn: sqlite3.Connection, kind: str = "table") -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


def test_corpus_schema(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "corpus.sqlite")
    assert current_version(conn) == 0
    assert migrate(conn, "corpus") == len(load_migrations("corpus")) >= 1
    assert tables(conn) == CORPUS_TABLES
    assert tables(conn, "view") == {"units"}
    assert current_version(conn) == len(load_migrations("corpus"))


def test_ops_schema() -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn, "ops")
    assert tables(conn) == OPS_TABLES
    conn.execute(
        "INSERT INTO traces (trace_id, question, model, surface_id, snapshot, started_at, header) "
        "VALUES ('t1', 'q', 'm', 'default@abc123', '2026.11.0', '2026-11-10T00:00:00Z', '{}')"
    )
    conn.execute(
        "INSERT INTO trace_events (trace_id, seq, t_ms, kind, event) VALUES ('t1', 0, 0, 'tool', '{}')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO trace_events (trace_id, seq, t_ms, kind, event) "
            "VALUES ('t1', 1, 5, 'bogus', '{}')"
        )


def test_migrating_twice_changes_nothing() -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn, "corpus")
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert migrate(conn, "corpus") == current_version(conn)
    assert conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before


def write(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


def test_upgrade_applies_only_new_migrations_and_keeps_data(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    v1 = write(
        tmp_path / "m", {"0001_first.sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT);"}
    )
    assert migrate(conn, v1) == 1
    conn.execute("INSERT INTO t (a) VALUES ('kept')")
    conn.commit()
    write(
        tmp_path / "m",
        {
            "0002_add_column.sql": "ALTER TABLE t ADD COLUMN b TEXT DEFAULT 'new';\n"
            "CREATE INDEX t_a ON t (a); -- two statements; and a ';' in a comment\n"
        },
    )
    assert migrate(conn, tmp_path / "m") == 2
    assert conn.execute("SELECT a, b FROM t").fetchall() == [("kept", "new")]
    assert current_version(conn) == 2


def test_a_failed_migration_rolls_back_completely(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    bad = write(
        tmp_path / "m",
        {
            "0001_ok.sql": "CREATE TABLE t (id INTEGER);",
            "0002_bad.sql": "CREATE TABLE u (id INTEGER);\nINSERT INTO nowhere VALUES (1);",
        },
    )
    with pytest.raises(MigrationError, match="0002_bad failed"):
        migrate(conn, bad)
    assert current_version(conn) == 1
    assert tables(conn) == {"t"}  # 0001 stayed, the half-applied 0002 did not


def test_migrations_must_be_numbered_without_gaps(tmp_path: Path) -> None:
    gap = write(tmp_path / "m", {"0001_a.sql": "SELECT 1;", "0003_c.sql": "SELECT 1;"})
    with pytest.raises(MigrationError, match="without gaps"):
        load_migrations(gap)


def test_a_database_from_the_future_is_refused() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 999")
    with pytest.raises(MigrationError, match="newer than this code"):
        migrate(conn, "corpus")


def test_schema_is_strict_about_ids(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn, "corpus")
    with pytest.raises(sqlite3.IntegrityError):  # doc_id must equal ns:local_id
        conn.execute(
            "INSERT INTO documents (doc_id, ns, local_id, kind, title, source_url, added_at) "
            "VALUES ('arxiv:1', 'acl', '1', 'paper', 't', 'u', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError):  # STRICT tables: no text in an integer column
        conn.execute(
            "INSERT INTO facts (subject, field, value, source, producer, retrieved_at, confidence) VALUES ('s','f','1','x','p','now','high')"
        )
