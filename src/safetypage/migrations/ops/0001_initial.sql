-- Mutable operational state: benchmark runs, traces, and the server's call log.
-- Corpus snapshots are immutable and live elsewhere; this is the only database that is migrated
-- in place and the only one that needs backing up.

CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,               -- ULID minted by the harness
    benchmark       TEXT NOT NULL,                  -- 'citationbench@1.0/dev'
    surface_id      TEXT NOT NULL,                  -- 'default@a1f3c9'
    snapshot        TEXT NOT NULL,                  -- corpus snapshot id
    arm             TEXT NOT NULL,                  -- retrieval arm
    server_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    solver          TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    record          TEXT NOT NULL DEFAULT '{}'      -- JSON: everything needed to rerun it
) STRICT;

-- One trace per question answered. The events are the contract in safetypage.trace.
CREATE TABLE traces (
    trace_id     TEXT PRIMARY KEY,
    run_id       TEXT REFERENCES runs (run_id),     -- NULL for an opted-in public session
    sample_id    TEXT,
    question     TEXT NOT NULL,
    model        TEXT NOT NULL,
    surface_id   TEXT NOT NULL,
    snapshot     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    header       TEXT NOT NULL,                     -- JSON: the trace's TraceHeader
    answer       TEXT,                              -- JSON: the trace's Answer, once scored
    scores       TEXT,                              -- JSON
    UNIQUE (run_id, sample_id)
) STRICT;

CREATE TABLE trace_events (
    trace_id  TEXT NOT NULL REFERENCES traces (trace_id),
    seq       INTEGER NOT NULL,
    t_ms      INTEGER NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('think', 'tool', 'answer', 'cite', 'verify')),
    event     TEXT NOT NULL,                        -- JSON: one TraceEvent
    PRIMARY KEY (trace_id, seq)
) STRICT, WITHOUT ROWID;

-- The server's own log, one row per tool call. Benchmark and opted-in calls keep their
-- arguments; public calls keep none (args is NULL) and never an IP address.
CREATE TABLE tool_calls (
    request_id      TEXT PRIMARY KEY,
    ts              TEXT NOT NULL,
    surface_id      TEXT NOT NULL,
    snapshot        TEXT NOT NULL,
    arm             TEXT NOT NULL,
    server_version  TEXT NOT NULL,
    tool            TEXT NOT NULL,
    client          TEXT,                           -- client family: 'claude.ai', 'inspect'
    run_id          TEXT,
    sample_id       TEXT,
    args            TEXT,                           -- JSON, or NULL for public traffic
    returned        TEXT NOT NULL DEFAULT '[]',     -- JSON array of cite strings, in order
    verdict         TEXT,
    result_tokens   INTEGER,
    latency_ms      INTEGER,
    cache_hit       INTEGER NOT NULL DEFAULT 0,
    error           TEXT
) STRICT;
CREATE INDEX tool_calls_run ON tool_calls (run_id, sample_id, ts);
