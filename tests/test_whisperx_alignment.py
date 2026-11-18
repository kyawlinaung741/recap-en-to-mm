from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recap_runtime.services.whisper_service import WhisperTimestampService


class WhisperXAlignmentTests(unittest.TestCase):
    def test_alignment_replaces_valid_word_timings_and_keeps_segment_boundaries(self):
        original = [{
            "id": 0,
            "start": 1.0,
            "end": 3.0,
            "text": "Hello world",
            "words": [{"start": 1.0, "end": 1.5, "text": "Hello"}],
        }]
        aligned = [{
            "start": 1.1,
            "end": 2.9,
            "text": "Hello world",
            "words": [
                {"start": 1.12, "end": 1.58, "word": "Hello"},
                {"start": 1.70, "end": 2.85, "word": "world"},
            ],
        }]
        got = WhisperTimestampService._merge_whisperx_segments(original, aligned)
        self.assertEqual((got[0]["start"], got[0]["end"]), (1.0, 3.0))
        self.assertEqual(got[0]["words"], [
            {"start": 1.12, "end": 1.58, "text": "Hello"},
            {"start": 1.7, "end": 2.85, "text": "world"},
        ])

    def test_invalid_alignment_falls_back_to_original_words(self):
        original = [{"start": 0.0, "end": 1.0, "words": [{"start": 0.1, "end": 0.8, "text": "ok"}]}]
        got = WhisperTimestampService._merge_whisperx_segments(
            original, [{"words": [{"word": "", "start": 0.0, "end": 0.0}]}]
        )
        self.assertEqual(got[0]["words"], original[0]["words"])

    def test_explicit_whisperx_falls_back_to_faster_backend(self):
        service = WhisperTimestampService(backend="whisperx")
        with mock.patch.object(service, "_load_whisperx", return_value=False), \
                mock.patch.object(service, "_load_faster_whisper", side_effect=lambda: setattr(service, "_active_backend", "faster-whisper") or True):
            service._ensure_model()
        self.assertEqual(service._active_backend, "faster-whisper")


if __name__ == "__main__":
    unittest.main()
