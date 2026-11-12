from __future__ import annotations

import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import core


class LongVideoSyncTests(unittest.TestCase):
    def test_cumulative_frame_clock_stays_bounded_over_seven_hours(self):
        frames_done = 0
        total_audio_seconds = 0.0
        total_frames = 0
        segment_count = 6387

        for index in range(segment_count):
            # Deterministic ~7-hour workload with thousands of short narration units.
            duration = 2.05 + (index % 20) * 0.2
            total_audio_seconds += duration
            count, frames_done = core.next_cumulative_frame_count(
                total_audio_seconds, frames_done, fps=30
            )
            self.assertGreaterEqual(count, 1)
            total_frames += count
            self.assertLessEqual(
                abs(frames_done / 30.0 - total_audio_seconds),
                1.0 / 60.0 + 1e-9,
            )

        self.assertEqual(total_frames, round(total_audio_seconds * 30))
        self.assertGreater(total_audio_seconds, 7 * 60 * 60 - 120)

    def test_wav_duration_uses_exact_sample_count_without_ffprobe(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "voice.wav"
            sample_rate = 48000
            sample_frames = 48000 * 7 + 12345
            with wave.open(str(path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(sample_rate)
                writer.writeframes(b"\\x00\\x00" * sample_frames)

            with mock.patch.object(
                core.subprocess, "run",
                side_effect=AssertionError("ffprobe should not be called for a WAV"),
            ):
                duration = core.probe_wav_duration("ffprobe", path)

            self.assertEqual(duration, sample_frames / sample_rate)

    def test_rendered_segments_use_one_cfr_30fps_mp4_clock(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "part.mp4"

            def fake_run(cmd, **_kwargs):
                Path(cmd[-1]).write_bytes(b"video")
                return SimpleNamespace(returncode=0, stderr="")

            with mock.patch.object(core.subprocess, "run", side_effect=fake_run) as run:
                core.render_video_part(
                    "ffmpeg",
                    Path(td) / "source.mp4",
                    output,
                    {"video_start": 0.0, "video_end": 4.0},
                    3.0,
                    "libx264",
                    frame_count=90,
                )

            command = run.call_args.args[0]
            self.assertIn("-fps_mode", command)
            self.assertIn("cfr", command)
            self.assertIn("-r", command)
            self.assertIn("30", command)
            self.assertIn("-video_track_timescale", command)
            self.assertIn("30000", command)
            self.assertIn("-frames:v", command)
            self.assertIn("90", command)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
