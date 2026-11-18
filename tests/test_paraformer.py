from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import recap_planner as rp  # noqa: E402
from recap_runtime.services.whisper_service import WhisperTimestampService  # noqa: E402


class ParaformerTests(unittest.TestCase):
    def test_paraformer_sentence_info_is_normalized_to_seconds(self):
        service = WhisperTimestampService(backend="paraformer-zh", language="zh")
        service._model = mock.Mock()
        service._model.generate.return_value = [{
            "text": "你好世界",
            "sentence_info": [
                {"text": "你好", "start": 0, "end": 1200},
                {"text": "世界", "start": 1250, "end": 2400},
            ],
        }]
        result = service._transcribe_paraformer("movie.wav", media_duration=3.0)
        self.assertEqual(result["backend"], "paraformer-zh")
        self.assertEqual(result["language"], "zh")
        self.assertEqual([(x["start"], x["end"]) for x in result["segments"]], [(0.0, 1.2), (1.25, 2.4)])
        service._model.generate.assert_called_once_with(input="movie.wav", batch_size_s=300)

    def test_only_chinese_selects_paraformer(self):
        self.assertEqual(rp.whisper_choice("zh"), ("paraformer-zh", "zh"))
        self.assertEqual(rp.whisper_choice("hi"), ("medium", "hi"))
        self.assertEqual(rp.whisper_choice("en"), ("small.en", "en"))


if __name__ == "__main__":
    unittest.main()
