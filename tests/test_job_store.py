from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recap_runtime.services.job_store import JobStore


class JobStoreTests(unittest.TestCase):
    def test_schema_and_job_progress_are_queryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.sqlite"
            store = JobStore(path)
            store.upsert_job("job-1", "movie.mp4", source_fingerprint="10:20")
            count = store.upsert_segments("job-1", [
                {"id": 12, "speech_start": 1.25, "speech_end": 3.5,
                 "source_text": "He runs.", "translation": "သူပြေးတယ်။"},
                {"id": 13, "video_start": 4, "video_end": 6, "source_text": "She waits."},
            ])
            store.upsert_asset("job-1", None, "final", "final.mp4", status="completed")
            store.set_status("job-1", "completed")
            self.assertEqual(count, 2)
            self.assertEqual(store.counts("job-1"), {
                "segments": 2, "translations": 2, "assets": 1, "errors": 0,
            })
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT status FROM jobs WHERE id='job-1'").fetchone()[0], "completed")
                self.assertEqual(db.execute(
                    "SELECT status FROM translations WHERE job_id='job-1' AND segment_id=12"
                ).fetchone()[0], "completed")
                self.assertEqual(db.execute(
                    "SELECT status FROM segments WHERE job_id='job-1' AND segment_id=13"
                ).fetchone()[0], "pending")

    def test_structured_error_is_mirrored_in_errors_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "job.sqlite")
            store.upsert_job("job-2", "movie.mp4")
            record = {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "job_id": "job-2",
                "segment_id": 7,
                "stage": "translation",
                "error_type": "quota",
                "message": "quota exceeded",
                "retryable": True,
                "retry_count": 1,
            }
            store.record_error(record)
            self.assertEqual(store.counts("job-2")["errors"], 1)
            with sqlite3.connect(store.path) as db:
                raw = db.execute("SELECT record_json FROM errors WHERE job_id='job-2'").fetchone()[0]
            self.assertEqual(json.loads(raw)["segment_id"], 7)


if __name__ == "__main__":
    unittest.main()
