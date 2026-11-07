"""Narration subtitles (subtitle_png.py: PNG cues burned in, SRT_for_upload) and video quality (core.py 1080/720/480)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import core as recap_core  # noqa: E402
import core  # noqa: E402
import subtitle_png  # noqa: E402


class PNGRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.tmp.name)
        cls.source, cls.output = cls.folder / "source.mp4", cls.folder / "subtitled.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=0x203048:s=640x360:r=30:d=4.5", "-c:v", "libx264", str(cls.source)], check=True)
        cls.track = subtitle_png.prepare([
            dict(start=.5, end=2., text=subtitle_png.SAMPLE),
            dict(start=2.5, end=4., text=subtitle_png.SAMPLE * 6),
        ], {"size": 28}, (640, 360), cls.folder, 4.5, log=lambda _m: None)
        recap_core.apply_production_overlays("ffmpeg", cls.source, cls.output,
                                            {"_subtitle_png_track": cls.track}, "libx264", cls.folder,
                                            frame_size=(640, 360))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frame(self, video, time):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(video), "-frames:v", "1",
                               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], check=True,
                              capture_output=True).stdout

    def test_png_has_alpha_and_long_text_keeps_original_interval(self):
        cues = self.track["cues"]
        self.assertGreater(len(cues), 2)
        self.assertEqual(cues[1]["start"], 2.5)
        self.assertEqual(cues[-1]["end"], 4.)
        for left, right in zip(cues[1:], cues[2:]):
            self.assertAlmostEqual(left["end"], right["start"], places=6)
        for cue in cues:
            self.assertLessEqual(len(cue["text"].splitlines()), 2)
            with Image.open(cue["png"]) as img:
                self.assertEqual(img.mode, "RGBA")
                self.assertEqual(img.getpixel((0, 0))[3], 0)
                self.assertIsNotNone(img.getbbox())

    def test_subtitles_appear_only_inside_their_cues_without_extending_video(self):
        for time in (.2, 2.2, 4.2):
            source, out = self.frame(self.source, time), self.frame(self.output, time)
            # The overlay pass converts RGB/YUV and encodes again (about one RGB level on this flat source).
            self.assertLess(sum(abs(a-b) for a, b in zip(source, out)) / len(source), 1.5)
        source, out = self.frame(self.source, 1.), self.frame(self.output, 1.)
        self.assertGreater(sum(abs(a-b) for a, b in zip(source, out)) / len(source), 3.)
        self.assertAlmostEqual(recap_core.probe_duration("ffprobe", self.output), 4.5, delta=.04)

    def test_srt_uses_voice_times_and_blank_track_ends_transparently(self):
        text = Path(self.track["srt"]).read_text(encoding="utf-8")
        self.assertIn("00:00:00,500 --> 00:00:02,000", text)
        self.assertTrue(Path(self.track["timeline"]).read_text().endswith("option framerate 1000\n"))
        self.assertIn(subtitle_png.SAMPLE.split()[0], text)


class UploadSrtTests(unittest.TestCase):
    def test_srt_goes_to_srt_for_upload_not_beside_the_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "Movie_Myanmar.mp4"
            final.write_bytes(b"v")
            segs = [{"start": 0.5, "end": 2.0, "text": "ဇွန်ဘီ (Zombie) တွေ လာနေပြီ။"}, {"start": 2.0, "end": 2.0, "text": "x"},
                    {"start": 3.0, "end": 4.25, "text": "ပြေးကြ။"}]
            srt = subtitle_png.upload_srt(final, segs)
            self.assertEqual(srt, Path(tmp) / "SRT_for_upload" / "Movie_Myanmar.srt")
            self.assertFalse((Path(tmp) / "Movie_Myanmar.srt").exists())
            text = srt.read_text(encoding="utf-8")
            self.assertIn("00:00:00,500 --> 00:00:02,000\nဇွန်ဘီ တွေ လာနေပြီ။", text)   # gloss not shown
            self.assertIn("2\n00:00:03,000 --> 00:00:04,250\nပြေးကြ။", text)            # empty cue dropped
            burned = Path(tmp) / "cards.srt"
            burned.write_text("1\n00:00:00,000 --> 00:00:01,000\ncard\n", encoding="utf-8")
            self.assertEqual(subtitle_png.upload_srt(final, segs, burned).read_text(encoding="utf-8"),
                             burned.read_text(encoding="utf-8"))                       # same cards as the picture


class QualityTests(unittest.TestCase):
    def test_frame_sizes(self):
        self.assertEqual(core.output_canvas("16:9"), (1920, 1080))                    # as before
        self.assertEqual(core.output_canvas("16:9", quality="720"), (1280, 720))
        self.assertEqual(core.output_canvas("9:16", quality="720"), (720, 1280))
        self.assertEqual(core.output_canvas("9:16", quality="480"), (480, 854))
        self.assertEqual(core.output_canvas("1:1", quality="480"), (480, 480))
        self.assertEqual(core.output_canvas("Original", 3840, 1600, quality="720"), (1280, 534))

    def test_encoder_settings(self):
        self.assertEqual(core._encoder_args("libx264"), ["-c:v", "libx264", "-preset", "medium", "-crf", "18"])
        self.assertEqual(core._encoder_args("libx264", "720")[2:4], ["-preset", "veryfast"])
        self.assertEqual(core._encoder_args("libx264", "480")[2:4], ["-preset", "superfast"])
        self.assertEqual(core._encoder_args("h264_nvenc"),
                         ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"])

    def test_dual_gpu_encoder_selection(self):
        encoders = {"h264_nvenc", "h264_qsv"}
        self.assertEqual(core.choose_gpu_encoders("nvidia", encoders), ("h264_nvenc",))
        self.assertEqual(core.choose_gpu_encoders("intel", encoders), ("h264_qsv",))
        self.assertEqual(core.choose_gpu_encoders("both", encoders), ("h264_nvenc", "h264_qsv"))
        self.assertEqual([core.encoder_for_segment("both", i, encoders) for i in range(1, 5)],
                         ["h264_nvenc", "h264_qsv", "h264_nvenc", "h264_qsv"])
        self.assertEqual(core.encoder_for_segment("nvidia", 1, {"h264_qsv"}), "h264_qsv")
        self.assertEqual(core.encoder_for_segment("intel", 1, set()), "libx264")

    def test_unknown_or_old_values_are_1080(self):
        for value in (None, "", "1080p", "4k", 1080):
            self.assertEqual(core.video_quality(value), "1080")
        self.assertEqual(core.video_quality("720p"), "720")

    def test_subtitle_keeps_its_look_on_a_smaller_frame(self):
        s = subtitle_png.style({"size": 48, "shadow": 3, "outline_width": 4})
        small = subtitle_png.scaled(s, core.quality_scale("720"))
        self.assertEqual((small["size"], small["shadow"], small["outline_width"]), (32, 2, 3))
        self.assertEqual((small["width"], small["position"]), (s["width"], s["position"]))
        self.assertEqual(subtitle_png.scaled(s, 1.0), s)
        w1, h1, x1, y1 = subtitle_png.geometry(s, (1080, 1920))
        w2, h2, x2, y2 = subtitle_png.geometry(small, (720, 1280))
        self.assertAlmostEqual(w2 / 720, w1 / 1080, places=2)
        self.assertAlmostEqual(y2 / 1280, y1 / 1920, places=1)


if __name__ == "__main__":
    unittest.main()
