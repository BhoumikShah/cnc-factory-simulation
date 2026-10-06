from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from vmc_twin.domain.events import Event
from vmc_twin.domain.states import CauseCode, SpindleState


class EventStore:
    """
    High-performance, embedded event store for discrete simulation events.
    Uses SQLite with WAL mode by default; supports export to Pandas/Polars/Parquet.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.conn.execute("PRAGMA synchronous = NORMAL;")
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    t_start REAL NOT NULL,
                    t_end REAL NOT NULL,
                    machine_id TEXT NOT NULL,
                    job_id TEXT,
                    op_id TEXT,
                    state TEXT NOT NULL,
                    cause_code TEXT NOT NULL,
                    duration REAL NOT NULL,
                    metadata_json TEXT
                );
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_machine_time ON events(machine_id, t_start, t_end);"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);"
            )

    def insert_event(self, event: Event) -> None:
        """Inserts a single simulation event."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO events (
                    t_start, t_end, machine_id, job_id, op_id, state, cause_code, duration, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.t_start,
                    event.t_end,
                    event.machine_id,
                    event.job_id,
                    event.op_id,
                    event.state.value,
                    event.cause_code.value,
                    event.duration(),
                    json.dumps(event.metadata) if event.metadata else None,
                ),
            )

    def insert_events(self, events: Sequence[Event]) -> None:
        """Batch insert simulation events for maximum throughput."""
        if not events:
            return
        records = [
            (
                e.t_start,
                e.t_end,
                e.machine_id,
                e.job_id,
                e.op_id,
                e.state.value,
                e.cause_code.value,
                e.duration(),
                json.dumps(e.metadata) if e.metadata else None,
            )
            for e in events
        ]
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO events (
                    t_start, t_end, machine_id, job_id, op_id, state, cause_code, duration, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

    def get_all_events(self) -> list[Event]:
        """Retrieves all stored events ordered by start time."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY t_start ASC, id ASC")
        rows = cursor.fetchall()
        events: list[Event] = []
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            events.append(
                Event(
                    t_start=row["t_start"],
                    t_end=row["t_end"],
                    machine_id=row["machine_id"],
                    job_id=row["job_id"],
                    op_id=row["op_id"],
                    state=SpindleState(row["state"]),
                    cause_code=CauseCode(row["cause_code"]),
                    metadata=meta,
                )
            )
        return events

    def get_events_in_window(self, t_min: float, t_max: float) -> list[Event]:
        """Retrieves events that overlap with the interval [t_min, t_max]."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events 
            WHERE t_end > ? AND t_start < ?
            ORDER BY t_start ASC
            """,
            (t_min, t_max),
        )
        rows = cursor.fetchall()
        events: list[Event] = []
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            events.append(
                Event(
                    t_start=row["t_start"],
                    t_end=row["t_end"],
                    machine_id=row["machine_id"],
                    job_id=row["job_id"],
                    op_id=row["op_id"],
                    state=SpindleState(row["state"]),
                    cause_code=CauseCode(row["cause_code"]),
                    metadata=meta,
                )
            )
        return events

    def count_events(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        return int(cursor.fetchone()[0])

    def close(self) -> None:
        self.conn.close()
