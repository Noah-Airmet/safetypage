"""The server's call log: one ``tool_calls`` row in ``ops.sqlite`` per call.

Calls that carry a benchmark run id (``X-OnThePage-Run``) are logged in full: arguments, the
cite strings returned, the error message. Public calls keep no arguments, no returned cites and
no error text (which can echo what was asked), only the error's kind. No IP address is ever
written.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from onthepage.corpus import utc_now
from onthepage.migrate import migrate

__all__ = ["CallRecord", "OpsLog"]

_INSERT = (
    "INSERT INTO tool_calls (request_id, ts, surface_id, snapshot, arm, server_version, tool, "
    "client, run_id, sample_id, args, returned, verdict, result_tokens, latency_ms, error) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(slots=True)
class CallRecord:
    request_id: str
    surface_id: str
    snapshot: str
    arm: str
    server_version: str
    tool: str
    client: str | None = None
    run_id: str | None = None
    sample_id: str | None = None
    args: dict[str, object] | None = None
    returned: list[str] = field(default_factory=list[str])
    verdict: str | None = None
    result_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    error_kind: str | None = None


class OpsLog:
    def __init__(self, path: Path | None) -> None:
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 2000")
            migrate(conn, "ops")
            self._conn = conn

    def write(self, record: CallRecord) -> None:
        if self._conn is None:
            return
        full = record.run_id is not None
        row = (
            record.request_id,
            utc_now(),
            record.surface_id,
            record.snapshot,
            record.arm,
            record.server_version,
            record.tool,
            record.client,
            record.run_id,
            record.sample_id if full else None,
            json.dumps(record.args, sort_keys=True) if full and record.args is not None else None,
            json.dumps(record.returned if full else []),
            record.verdict,
            record.result_tokens,
            record.latency_ms,
            (record.error if full else record.error_kind) if record.error else None,
        )
        with self._lock:
            self._conn.execute(_INSERT, row)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
