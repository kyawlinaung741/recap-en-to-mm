"""Gemini TTS narrator (app/gemini_tts.py): one voice for the whole video, keys, cache, quota rotation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import gemini_tts  # noqa: E402


def env_file(tmp: str, text: str) -> str:
    path = Path(tmp) / ".env"
    path.write_text(text, encoding="utf-8")
    return str(path)


class PromptTests(unittest.TestCase):
    def test_every_line_gets_the_same_narrator(self):
        a = gemini_tts.narrator_prompt("ပထမ စာကြောင်း။", "gemini:Charon")
        b = gemini_tts.narrator_prompt("ဒုတိယ (Zombie) စာကြောင်း။", "gemini:Charon")
        self.assertEqual(a.split("TRANSCRIPT:")[0], b.split("TRANSCRIPT:")[0])     # identical direction
        self.assertIn("ONE CONTINUOUS NARRATOR", a)
        self.assertIn("Never impersonate a character, change gender or become a second speaker", a)
        self.assertIn("ONE adult male Burmese narrator", a)
        self.assertNotIn("Zombie", b)                                                  # glosses are not read
        self.assertIn("ONE adult female", gemini_tts.narrator_prompt("x", "gemini:Kore"))

    def test_keys_in_number_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = env_file(tmp, "GEMINI_IMAGE_PROJECT_10_KEY=k10\nGEMINI_IMAGE_PROJECT_2_KEY=k2\nGEMINI_API_KEY=main\n")
            self.assertEqual(gemini_tts.read_keys(env), ["k2", "k10"])
            self.assertEqual(gemini_tts.read_keys(env_file(tmp, "GEMINI_API_KEY=main\n")), ["main"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = env_file(self.tmp.name, "GEMINI_IMAGE_PROJECT_1_KEY=a\nGEMINI_IMAGE_PROJECT_2_KEY=b\n")

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, direction=""):
        return gemini_tts.GeminiTTSEngine(ffmpeg="ffmpeg", work_dir=Path(self.tmp.name) / "w", rate="+0%",
                                          env_file=self.env, direction=direction, log=lambda *_: None)

    def test_a_line_is_made_once_and_then_reused(self):
        eng = self.engine()
        pcm = b"\x00\x10" * 24000
        with mock.patch.object(eng, "_ask", return_value=pcm) as ask:
            first = eng.generate_channel99_voice("မင်္ဂလာပါ။", "gemini:Charon")
            again = eng.generate_channel99_voice("မင်္ဂလာပါ။", "gemini:Charon")
        self.assertEqual(first, again)
        self.assertEqual(ask.call_count, 1)
        self.assertGreater(first.stat().st_size, 1000)
        self.assertEqual(ask.call_args.args[1], "Charon")

    def test_style_or_speed_change_makes_new_audio(self):
        self.assertNotEqual(self.engine().fingerprint("gemini:Charon"),
                            self.engine("calm storyteller").fingerprint("gemini:Charon"))

    def test_used_up_key_is_skipped(self):
        eng = self.engine()
        calls = []

        class Quota(Exception):
            code = 429

        def client(key):
            def generate_content(model, contents, config):
                calls.append((key, model))
                if key == "a":
                    raise Quota("RESOURCE_EXHAUSTED")
                part = SimpleNamespace(inline_data=SimpleNamespace(data=b"pcm"))
                return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
            return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
        with mock.patch.object(gemini_tts, "_client", client):
            self.assertEqual(eng._ask("p", "Charon"), b"pcm")
            self.assertEqual(eng._ask("p", "Charon"), b"pcm")
        self.assertEqual([c[0] for c in calls], ["a", "b", "b"])      # key a not asked again after its 429

    def test_no_keys(self):
        import os
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(gemini_tts.GeminiTTSError):
            gemini_tts.GeminiTTSEngine(ffmpeg="ffmpeg", work_dir=Path(self.tmp.name), rate="+0%",
                                       env_file=env_file(self.tmp.name, "X=1\n"), log=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
