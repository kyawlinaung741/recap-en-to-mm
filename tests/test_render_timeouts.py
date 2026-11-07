from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import core


class EdgeTtsTimeoutTests(unittest.TestCase):
    def test_websocket_save_is_cancelled_at_timeout(self):
        class SlowCommunicate:
            def __init__(self, *args, **kwargs):
                pass

            async def save(self, path):
                await asyncio.sleep(0.1)

        engine = object.__new__(core.EdgeTTSEngine)
        engine.rate = "+0%"
        engine.pitch = "+0Hz"
        engine.request_timeout_seconds = 0.01
        fake_edge_tts = SimpleNamespace(Communicate=SlowCommunicate)

        with mock.patch.dict(sys.modules, {"edge_tts": fake_edge_tts}):
            with self.assertRaisesRegex(TimeoutError, "timed out after"):
                asyncio.run(engine._save_mp3_async("hello", "en-US-AriaNeural", Path("out.mp3")))


class RenderTimeoutTests(unittest.TestCase):
    def test_hardware_timeout_is_bounded_and_cpu_fallback_gets_more_time(self):
        hardware = core._render_timeout_seconds(3.0, "h264_qsv")
        cpu = core._render_timeout_seconds(3.0, "libx264")
        self.assertEqual(hardware, 96.0)
        self.assertGreater(cpu, hardware)

    def test_timed_out_render_removes_incomplete_output(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "segment.mp4"

            def fake_run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"partial output")
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

            with mock.patch.object(core.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(TimeoutError, "h264_qsv.*timed out"):
                    core.render_video_part(
                        "ffmpeg", Path(td) / "source.mp4", output,
                        {"video_start": 0.0, "video_end": 1.0},
                        1.0, "h264_qsv", timeout_seconds=0.01,
                    )

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
