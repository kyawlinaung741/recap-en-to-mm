from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recap_runtime.services.structured_logger import append_error, classify_error, error_log_path


class StructuredLoggingTests(unittest.TestCase):
    def test_error_log_path_is_a_job_sidecar(self):
        self.assertEqual(error_log_path("jobs/demo"), Path("jobs/demo/errors.jsonl"))

    def test_quota_error_is_retryable_and_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "errors.jsonl"
            record = append_error(
                path,
                job_id="movie-001",
                stage="translation",
                role="translation",
                model="gemini-4-hydrogen",
                key_index=2,
                segment_id=1240,
                message="Resource exhausted: quota exceeded",
                retry_count=1,
                details={"batch": "01240-01259"},
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved, record)
            self.assertEqual(record["error_type"], "quota")
            self.assertTrue(record["retryable"])
            self.assertEqual(record["key_index"], 2)
            self.assertEqual(record["segment_id"], 1240)
            self.assertEqual(record["details"]["batch"], "01240-01259")
            self.assertTrue(record["timestamp"].endswith("+00:00"))

    def test_duplicate_translation_is_machine_classified(self):
        error_type, retryable = classify_error(
            "IDs 01240 and 01242 may say the same thing twice",
            stage="translation",
        )
        self.assertEqual(error_type, "duplicate_translation")
        self.assertTrue(retryable)

    def test_logger_never_raises_when_path_is_not_writable(self):
        record = append_error(
            Path("/dev/null") / "cannot-write.jsonl",
            stage="render",
            message="ffmpeg failed",
        )
        self.assertEqual(record["error_type"], "ffmpeg")


if __name__ == "__main__":
    unittest.main()
