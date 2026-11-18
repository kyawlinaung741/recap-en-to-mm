"""SQLite sidecar state for resumable Recap jobs.

JSON checkpoints remain authoritative for backward compatibility. This store is
an indexed, queryable mirror used for job status, segment progress, and future
selective retry tooling.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    job_id TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    start_time REAL NOT NULL DEFAULT 0,
    end_time REAL NOT NULL DEFAULT 0,
    source_text TEXT NOT NULL DEFAULT '',
    speaker TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS translations (
    job_id TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    attempt INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id),
    FOREIGN KEY (job_id, segment_id) REFERENCES segments(job_id, segment_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assets (
    job_id TEXT NOT NULL,
    segment_id INTEGER,
    asset_type TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    duration REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, segment_id, asset_type),
    FOREIGN KEY (job_id, segment_id) REFERENCES segments(job_id, segment_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    segment_id INTEGER,
    stage TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL,
    retryable INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    record_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_segments_status ON segments(job_id, status);
CREATE INDEX IF NOT EXISTS idx_errors_job ON errors(job_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class JobStore:
    """Small per-job SQLite store; each operation uses a short-lived connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def upsert_job(self, job_id: str, source_path: str, *, source_fingerprint: str = "",
                   status: str = "running") -> None:
        now = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO jobs(id, source_path, source_fingerprint, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET source_path=excluded.source_path,
                   source_fingerprint=excluded.source_fingerprint, status=excluded.status,
                   updated_at=excluded.updated_at""",
                (str(job_id), str(source_path), str(source_fingerprint), str(status), now, now),
            )

    def set_status(self, job_id: str, status: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (str(status), _now(), str(job_id)))

    def upsert_segments(self, job_id: str, segments: Iterable[dict[str, Any]]) -> int:
        now = _now()
        rows = []
        translations = []
        for segment in segments:
            try:
                segment_id = int(segment.get("id"))
            except (TypeError, ValueError):
                continue
            start = segment.get("speech_start", segment.get("video_start", segment.get("start", 0)))
            end = segment.get("speech_end", segment.get("video_end", segment.get("end", 0)))
            translation = str(segment.get("translation") or segment.get("narration") or "").strip()
            rows.append((str(job_id), segment_id, _number(start), _number(end),
                         str(segment.get("source_text") or ""), str(segment.get("speaker") or ""),
                         "translated" if translation else "pending", now))
            translations.append((str(job_id), segment_id, translation,
                                 str(segment.get("model") or ""), 0,
                                 "completed" if translation else "pending", now))
        with self._connect() as db:
            db.executemany(
                """INSERT INTO segments(job_id, segment_id, start_time, end_time, source_text, speaker, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, segment_id) DO UPDATE SET start_time=excluded.start_time,
                   end_time=excluded.end_time, source_text=excluded.source_text, speaker=excluded.speaker,
                   status=excluded.status, updated_at=excluded.updated_at""",
                rows,
            )
            db.executemany(
                """INSERT INTO translations(job_id, segment_id, text, model, attempt, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, segment_id) DO UPDATE SET text=excluded.text,
                   model=excluded.model, status=excluded.status, updated_at=excluded.updated_at""",
                translations,
            )
        return len(rows)

    def upsert_asset(self, job_id: str, segment_id: int | None, asset_type: str, path: str = "",
                     duration: float | None = None, status: str = "completed") -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO assets(job_id, segment_id, asset_type, path, duration, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, segment_id, asset_type) DO UPDATE SET path=excluded.path,
                   duration=excluded.duration, status=excluded.status, updated_at=excluded.updated_at""",
                (str(job_id), int(segment_id) if segment_id is not None else None, str(asset_type),
                 str(path), duration, str(status), _now()),
            )

    def record_error(self, record: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO errors(job_id, segment_id, stage, error_type, message, retryable,
                   retry_count, record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(record.get("job_id") or ""), record.get("segment_id"),
                 str(record.get("stage") or "unknown"), str(record.get("error_type") or "unknown"),
                 str(record.get("message") or ""), int(bool(record.get("retryable"))),
                 int(record.get("retry_count") or 0), json.dumps(record, ensure_ascii=False),
                 str(record.get("timestamp") or _now())),
            )

    def counts(self, job_id: str) -> dict[str, int]:
        with self._connect() as db:
            result = {}
            for table in ("segments", "translations", "assets", "errors"):
                column = "job_id"
                result[table] = int(db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (str(job_id),)
                ).fetchone()[0])
            return result
