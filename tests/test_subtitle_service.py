from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from subtitle_service import POSITIONS, subtitle_segments, write_srt  # noqa: E402


class SubtitleServiceTests(unittest.TestCase):
    def test_subtitles_follow_actual_tts_audio_timeline(self):
        plan = {
            "segments": [{"video_start": 50, "video_end": 60, "narration": "မူရင်း timing မသုံးရ"}],
            "tts_timing_segments": [
                {"audio_start": 0.0, "audio_end": 1.25, "text": "ပထမစာကြောင်း။"},
                {"audio_start": 1.25, "audio_end": 3.5, "text": "ဒုတိယစာကြောင်း။"},
            ],
        }
        rows = subtitle_segments(plan)
        self.assertEqual(rows[0]["start"], 0.0)
        self.assertEqual(rows[1]["end"], 3.5)
        self.assertEqual(len(rows), 2)

    def test_srt_is_utf8_and_uses_millisecond_timestamps(self):
        plan = {"tts_timing_segments": [{"audio_start": 0, "audio_end": 1.25, "text": "မင်္ဂလာပါ။"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = write_srt(plan, Path(folder) / "subtitles.srt")
            content = path.read_text(encoding="utf-8-sig")
        self.assertIn("00:00:00,000 --> 00:00:01,250", content)
        self.assertIn("မင်္ဂလာပါ။", content)

    def test_position_mapping_supports_top_middle_bottom(self):
        self.assertEqual(POSITIONS["Top Center"], 8)
        self.assertEqual(POSITIONS["Center"], 5)
        self.assertEqual(POSITIONS["Bottom Center"], 2)


if __name__ == "__main__":
    unittest.main()
