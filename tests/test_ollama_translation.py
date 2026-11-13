"""Local Ollama translation client contract tests; no Ollama server is required."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from recap_planner import OllamaTranslationClient


class OllamaTranslationClientTests(unittest.TestCase):
    def test_gemini_schema_types_are_converted_to_json_schema_types(self):
        source = {
            "type": "OBJECT",
            "properties": {
                "items": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {"id": {"type": "INTEGER"}, "translation": {"type": "STRING"}},
                    },
                }
            },
        }
        converted = OllamaTranslationClient._ollama_schema(source)
        self.assertEqual(converted["type"], "object")
        self.assertEqual(converted["properties"]["items"]["type"], "array")
        self.assertEqual(converted["properties"]["items"]["items"]["properties"]["id"]["type"], "integer")
        self.assertEqual(converted["properties"]["items"]["items"]["properties"]["translation"]["type"], "string")

    def test_generate_json_uses_local_chat_endpoint_and_parses_result(self):
        client = OllamaTranslationClient()
        response = mock.Mock()
        response.json.return_value = {"message": {"content": '{"items":[{"id":1,"translation":"သူ ပြန်လာတယ်။"}]}'}}
        response.raise_for_status.return_value = None
        with mock.patch.object(client.session, "post", return_value=response) as post:
            result = client.generate_json("translate", {
                "type": "OBJECT",
                "properties": {"items": {"type": "ARRAY", "items": {"type": "OBJECT"}}},
            })
        self.assertEqual(result["items"][0]["id"], 1)
        self.assertEqual(result["items"][0]["translation"], "သူ ပြန်လာတယ်။")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(kwargs["json"]["model"], "qwen3:4b")
        self.assertEqual(kwargs["json"]["format"]["type"], "object")
        self.assertFalse(kwargs["json"]["stream"])

    def test_thinking_tags_are_removed_before_json_parsing(self):
        client = OllamaTranslationClient()
        response = mock.Mock()
        response.json.return_value = {"message": {"content": '<think>reasoning</think>{"items":[]}' }}
        response.raise_for_status.return_value = None
        with mock.patch.object(client.session, "post", return_value=response):
            self.assertEqual(client.generate_json("translate"), {"items": []})


if __name__ == "__main__":
    unittest.main()
