import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from recap_planner import GEMINI_MODEL_FALLBACK_CHAIN, _STORY_CONTEXT_RESPONSE_SCHEMA


class GeminiSchemaTests(unittest.TestCase):
    def test_every_story_context_array_declares_string_items(self):
        properties = _STORY_CONTEXT_RESPONSE_SCHEMA["properties"]
        required = _STORY_CONTEXT_RESPONSE_SCHEMA["required"]

        self.assertEqual(set(properties), set(required))
        for name in required:
            with self.subTest(field=name):
                self.assertEqual(properties[name]["type"], "ARRAY")
                self.assertEqual(properties[name]["items"]["type"], "STRING")

    def test_current_gemini_models_are_in_fallback_chain(self):
        self.assertEqual(GEMINI_MODEL_FALLBACK_CHAIN[0], "gemini-3.8-flash")
        self.assertIn("gemini-4-argon", GEMINI_MODEL_FALLBACK_CHAIN)


if __name__ == "__main__":
    unittest.main()
