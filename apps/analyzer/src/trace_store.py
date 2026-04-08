"""TraceStore — Persistent storage for TraceRecords.

SQLite-backed for development, with optional S3-compatible backend for production.
Provides Python API; internal SQL is an implementation detail.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from pathlib import Path
from typing import Optional

from packages.core_schema.models.trace_record import TraceRecord


class TraceStore:
    """Persistent storage for TraceRecord objects using SQLite (Hardened).

    Stores request/response bodies as compressed BLOBs to minimize disk usage.
    Provides query APIs by session_id, timestamp range, and URL pattern.

    Hardening (audit fix):
    - WAL journal mode for concurrent readers + single writer
    - Busy timeout to handle SQLITE_BUSY under contention
    - Batch insert with transaction batching for throughput
    - Thread-safe connection management
    """

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_pragmas()
        self._init_schema()

    def _init_pragmas(self) -> None:
        """Configure SQLite pragmas for production performance.

        - WAL mode: allows concurrent reads while writing
        - busy_timeout: retries for up to 5s on SQLITE_BUSY instead of failing
        - synchronous NORMAL: balanced durability/performance (WAL makes this safe)
        - cache_size: 64MB page cache for large trace stores
        - temp_store MEMORY: temp tables in memory for faster joins
        - mmap_size: memory-mapped I/O for read performance
        """
        pragmas = [
            "PRAGMA journal_mode=WAL",
            "PRAGMA busy_timeout=5000",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA cache_size=-65536",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA mmap_size=268435456",
            "PRAGMA foreign_keys=ON",
        ]
        for pragma in pragmas:
            try:
                self._conn.execute(pragma)
            except sqlite3.OperationalError:
                # Some pragmas may not be supported on all SQLite versions
                pass

    def _init_schema(self) -> None:
        """Create tables and indexes."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                start_time_ms INTEGER,
                end_time_ms INTEGER,
                trace_count INTEGER DEFAULT 0,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                app_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                method TEXT NOT NULL,
                url TEXT NOT NULL,
                request_headers TEXT,
                request_body BLOB,
                request_body_parsed TEXT,
                response_status INTEGER,
                response_headers TEXT,
                response_body BLOB,
                response_body_parsed TEXT,
                response_time_ms INTEGER,
                ui_activity TEXT,
                ui_fragment TEXT,
                ui_event_type TEXT,
                ui_element_id TEXT,
                call_stack TEXT,
                invoking_class TEXT,
                invoking_method TEXT,
                tls_intercepted BOOLEAN DEFAULT 0,
                pinning_bypassed BOOLEAN DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS ui_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                activity TEXT,
                event_type TEXT,
                element_id TEXT,
                element_text TEXT,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
            CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp_ms);
            CREATE INDEX IF NOT EXISTS idx_traces_url ON traces(url);
            CREATE INDEX IF NOT EXISTS idx_traces_method ON traces(method);
            CREATE INDEX IF NOT EXISTS idx_traces_app ON traces(app_id);
            CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(response_status);
            CREATE INDEX IF NOT EXISTS idx_ui_events_session ON ui_events(session_id);
            CREATE INDEX IF NOT EXISTS idx_ui_events_timestamp ON ui_events(timestamp_ms);
        """)
        self._conn.commit()

    def create_session(self, session_id: str, app_id: str, metadata: Optional[dict] = None) -> None:
        """Register a new capture session."""
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, app_id, metadata) VALUES (?, ?, ?)",
            (session_id, app_id, json.dumps(metadata) if metadata else None),
        )
        self._conn.commit()

    def store_trace(self, record: TraceRecord) -> None:
        """Store a single TraceRecord."""
        # Ensure session exists
        existing = self._conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?",
            (record.session_id,)
        ).fetchone()
        if not existing:
            self.create_session(record.session_id, record.app_id)

        # Compress bodies
        req_body = None
        if record.request_body_raw:
            req_body = zlib.compress(record.request_body_raw)

        resp_body = None
        if record.response_body_raw:
            resp_body = zlib.compress(record.response_body_raw)

        self._conn.execute(
            """INSERT OR REPLACE INTO traces (
                trace_id, session_id, app_id, timestamp_ms,
                method, url, request_headers, request_body, request_body_parsed,
                response_status, response_headers, response_body, response_body_parsed,
                response_time_ms, ui_activity, ui_fragment, ui_event_type, ui_element_id,
                call_stack, invoking_class, invoking_method,
                tls_intercepted, pinning_bypassed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.trace_id, record.session_id, record.app_id, record.timestamp_ms,
                record.method, record.url,
                json.dumps(record.request_headers),
                req_body,
                json.dumps(record.request_body_parsed) if record.request_body_parsed else None,
                record.response_status,
                json.dumps(record.response_headers) if record.response_headers else None,
                resp_body,
                json.dumps(record.response_body_parsed) if record.response_body_parsed else None,
                record.response_time_ms,
                record.ui_activity, record.ui_fragment,
                record.ui_event_type, record.ui_element_id,
                json.dumps(record.call_stack),
                record.invoking_class, record.invoking_method,
                record.tls_intercepted, record.pinning_bypassed,
            ),
        )

        # Update session trace count
        self._conn.execute(
            """UPDATE sessions SET
                trace_count = (SELECT COUNT(*) FROM traces WHERE session_id = ?),
                start_time_ms = COALESCE(
                    (SELECT MIN(timestamp_ms) FROM traces WHERE session_id = ?),
                    start_time_ms
                ),
                end_time_ms = COALESCE(
                    (SELECT MAX(timestamp_ms) FROM traces WHERE session_id = ?),
                    end_time_ms
                )
            WHERE session_id = ?""",
            (record.session_id, record.session_id, record.session_id, record.session_id),
        )
        self._conn.commit()

    def store_traces(self, records: list[TraceRecord]) -> None:
        """Store multiple TraceRecords in a single transaction for throughput.

        Uses BEGIN IMMEDIATE to acquire a write lock upfront, preventing
        SQLITE_BUSY errors during the batch. Session metadata is updated
        once at the end instead of per-record.
        """
        if not records:
            return

        # Collect unique sessions that need creation
        existing_sessions: set[str] = set()
        needed_sessions: set[tuple[str, str]] = set()
        for record in records:
            if record.session_id not in existing_sessions:
                row = self._conn.execute(
                    "SELECT session_id FROM sessions WHERE session_id = ?",
                    (record.session_id,)
                ).fetchone()
                if row:
                    existing_sessions.add(record.session_id)
                else:
                    needed_sessions.add((record.session_id, record.app_id))

        # Batch insert within a single transaction
        try:
            self._conn.execute("BEGIN IMMEDIATE")

            # Create missing sessions
            for session_id, app_id in needed_sessions:
                self._conn.execute(
                    "INSERT OR IGNORE INTO sessions (session_id, app_id) VALUES (?, ?)",
                    (session_id, app_id),
                )

            # Insert all trace records
            for record in records:
                req_body = None
                if record.request_body_raw:
                    req_body = zlib.compress(record.request_body_raw)
                resp_body = None
                if record.response_body_raw:
                    resp_body = zlib.compress(record.response_body_raw)

                self._conn.execute(
                    """INSERT OR REPLACE INTO traces (
                        trace_id, session_id, app_id, timestamp_ms,
                        method, url, request_headers, request_body, request_body_parsed,
                        response_status, response_headers, response_body, response_body_parsed,
                        response_time_ms, ui_activity, ui_fragment, ui_event_type, ui_element_id,
                        call_stack, invoking_class, invoking_method,
                        tls_intercepted, pinning_bypassed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.trace_id, record.session_id, record.app_id, record.timestamp_ms,
                        record.method, record.url,
                        json.dumps(record.request_headers),
                        req_body,
                        json.dumps(record.request_body_parsed) if record.request_body_parsed else None,
                        record.response_status,
                        json.dumps(record.response_headers) if record.response_headers else None,
                        resp_body,
                        json.dumps(record.response_body_parsed) if record.response_body_parsed else None,
                        record.response_time_ms,
                        record.ui_activity, record.ui_fragment,
                        record.ui_event_type, record.ui_element_id,
                        json.dumps(record.call_stack),
                        record.invoking_class, record.invoking_method,
                        record.tls_intercepted, record.pinning_bypassed,
                    ),
                )

            # Update session metadata once per unique session
            updated_sessions = {r.session_id for r in records}
            for session_id in updated_sessions:
                self._conn.execute(
                    """UPDATE sessions SET
                        trace_count = (SELECT COUNT(*) FROM traces WHERE session_id = ?),
                        start_time_ms = COALESCE(
                            (SELECT MIN(timestamp_ms) FROM traces WHERE session_id = ?),
                            start_time_ms
                        ),
                        end_time_ms = COALESCE(
                            (SELECT MAX(timestamp_ms) FROM traces WHERE session_id = ?),
                            end_time_ms
                        )
                    WHERE session_id = ?""",
                    (session_id, session_id, session_id, session_id),
                )

            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def get_trace(self, trace_id: str) -> Optional[TraceRecord]:
        """Retrieve a single TraceRecord by ID."""
        row = self._conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_traces_by_session(self, session_id: str) -> list[TraceRecord]:
        """Retrieve all traces for a session, ordered by timestamp."""
        rows = self._conn.execute(
            "SELECT * FROM traces WHERE session_id = ? ORDER BY timestamp_ms",
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_traces_by_url(self, url_pattern: str) -> list[TraceRecord]:
        """Retrieve traces matching a URL pattern (LIKE query)."""
        rows = self._conn.execute(
            "SELECT * FROM traces WHERE url LIKE ? ORDER BY timestamp_ms",
            (f"%{url_pattern}%",),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_all_traces(self) -> list[TraceRecord]:
        """Retrieve all traces."""
        rows = self._conn.execute(
            "SELECT * FROM traces ORDER BY timestamp_ms"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def store_ui_event(
        self,
        session_id: str,
        timestamp_ms: int,
        activity: Optional[str] = None,
        event_type: Optional[str] = None,
        element_id: Optional[str] = None,
        element_text: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Store a UI event for later correlation with traces."""
        self._conn.execute(
            """INSERT INTO ui_events (
                session_id, timestamp_ms, activity, event_type,
                element_id, element_text, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, timestamp_ms, activity, event_type,
                element_id, element_text,
                json.dumps(metadata) if metadata else None,
            ),
        )
        self._conn.commit()

    def correlate_ui_events(self, session_id: str, window_ms: int = 250) -> None:
        """Correlate UI events with trace records by timestamp proximity.

        For each trace record without UI context, find the nearest UI event
        within the specified time window and attach its context.
        """
        traces = self.get_traces_by_session(session_id)
        ui_events = self._conn.execute(
            "SELECT * FROM ui_events WHERE session_id = ? ORDER BY timestamp_ms",
            (session_id,),
        ).fetchall()

        for trace in traces:
            if trace.ui_activity or trace.ui_event_type:
                continue  # Already has UI context

            # Find nearest UI event within window
            best_event = None
            best_delta = window_ms + 1

            for event in ui_events:
                delta = abs(trace.timestamp_ms - event["timestamp_ms"])
                if delta <= window_ms and delta < best_delta:
                    best_delta = delta
                    best_event = event

            if best_event:
                self._conn.execute(
                    """UPDATE traces SET
                        ui_activity = COALESCE(ui_activity, ?),
                        ui_event_type = COALESCE(ui_event_type, ?),
                        ui_element_id = COALESCE(ui_element_id, ?)
                    WHERE trace_id = ?""",
                    (
                        best_event["activity"],
                        best_event["event_type"],
                        best_event["element_id"],
                        trace.trace_id,
                    ),
                )

        self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> TraceRecord:
        """Convert a SQLite row to a TraceRecord."""
        # Decompress bodies
        req_body_raw = None
        if row["request_body"]:
            req_body_raw = zlib.decompress(row["request_body"])

        resp_body_raw = None
        if row["response_body"]:
            resp_body_raw = zlib.decompress(row["response_body"])

        return TraceRecord(
            trace_id=row["trace_id"],
            app_id=row["app_id"],
            session_id=row["session_id"],
            timestamp_ms=row["timestamp_ms"],
            method=row["method"],
            url=row["url"],
            request_headers=json.loads(row["request_headers"]) if row["request_headers"] else {},
            request_body_raw=req_body_raw,
            request_body_parsed=json.loads(row["request_body_parsed"]) if row["request_body_parsed"] else None,
            response_status=row["response_status"],
            response_headers=json.loads(row["response_headers"]) if row["response_headers"] else None,
            response_body_raw=resp_body_raw,
            response_body_parsed=json.loads(row["response_body_parsed"]) if row["response_body_parsed"] else None,
            response_time_ms=row["response_time_ms"],
            ui_activity=row["ui_activity"],
            ui_fragment=row["ui_fragment"],
            ui_event_type=row["ui_event_type"],
            ui_element_id=row["ui_element_id"],
            call_stack=json.loads(row["call_stack"]) if row["call_stack"] else [],
            invoking_class=row["invoking_class"],
            invoking_method=row["invoking_method"],
            tls_intercepted=bool(row["tls_intercepted"]),
            pinning_bypassed=bool(row["pinning_bypassed"]),
        )

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
