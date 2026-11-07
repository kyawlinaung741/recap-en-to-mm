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
    def test_timeout_failure_retries_next_route_and_can_recover(self):
        with tempfile.TemporaryDirectory() as td:
            engine = object.__new__(core.EdgeTTSEngine)
            engine.work_dir = Path(td)
            engine.rate = "+0%"
            engine.pitch = "+0Hz"
            engine.request_timeout_seconds = 0.01
            engine.proxy = None
            engine.ffmpeg = "ffmpeg"
            engine.log = lambda _message: None
            engine._counter = 0
            attempts = []

            def synthesize(_text, _voice, mp3, *, direct):
                attempts.append(direct)
                if len(attempts) < 3:
                    raise TimeoutError("simulated Edge TTS timeout")
                mp3.write_bytes(b"x" * 300)

            def convert(cmd, **_kwargs):
                Path(cmd[-1]).write_bytes(b"wav-data")
                return SimpleNamespace(returncode=0, stderr="")

            with mock.patch.object(engine, "_synthesize_once", side_effect=synthesize), \
                 mock.patch.object(core.subprocess, "run", side_effect=convert), \
                 mock.patch.object(core.time, "sleep"):
                result = engine.generate_channel99_voice("hello there", "en-US-AriaNeural")

            self.assertEqual(len(attempts), 3)
            self.assertEqual(attempts, [True, True, False])
            self.assertTrue(Path(result).is_file())

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
