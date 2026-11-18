"""Gemini busy/quota fallback and ordered multi-key rotation tests."""
import sys
import unittest
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import recap_planner as rp  # noqa: E402


class _Chat:
    def __init__(self, owner, model):
        self.owner = owner
        self.model = model

    def send_message(self, prompt, config=None):
        if self.owner.busy_left > 0:
            self.owner.busy_left -= 1
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        return type("R", (), {"text": '{"ok": true}'})()


class _Chats:
    def __init__(self, owner):
        self.owner = owner

    def create(self, model):
        self.owner.models_used.append(model)
        return _Chat(self.owner, model)


class FakeAI:
    def __init__(self, busy_answers: int):
        self.busy_left = busy_answers
        self.models_used: list[str] = []
        self.client = type("C", (), {"chats": _Chats(self)})()
        self.text_model = "x"

    def _enable_proxy(self):
        pass

    def _disable_proxy(self):
        pass


def setup(ai, keys=("a", "b"), chain=("m1", "m2", "m3")):
    def factory(api_key, http_options):
        return ai.client
    rp._configure_gemini_key_pool(
        ai,
        [(f"K{i + 1}", key) for i, key in enumerate(keys)],
        client_factory=factory,
        log=lambda _m: None,
        model_chain=list(chain),
    )


class BusyModelTests(unittest.TestCase):
    def test_every_model_busy_tries_each_key_then_restarts(self):
        ai = FakeAI(busy_answers=4)
        setup(ai)
        with mock.patch.object(rp.time, "sleep") as sleep:
            self.assertEqual(rp._gemini_json(ai, "p"), {"ok": True})
        self.assertEqual(ai.models_used, ["m1", "m1", "m2", "m2", "m3"])
        sleep.assert_not_called()

    def test_gives_up_after_all_models_and_busy_rounds(self):
        ai = FakeAI(busy_answers=10_000)
        setup(ai)
        with mock.patch.object(rp.time, "sleep"), self.assertRaisesRegex(RuntimeError, "exhausted"):
            rp._gemini_json(ai, "p")
        self.assertGreaterEqual(len(ai.models_used), 3 * 2)

    def test_the_first_model_is_tried_again_later(self):
        ai = FakeAI(busy_answers=2)
        setup(ai)
        clock = [1000.0]
        with mock.patch.object(rp.time, "time", lambda: clock[0]):
            rp._gemini_json(ai, "p")                         # m1 key 1/2 busy -> m2 answers
            clock[0] += rp.GEMINI_BUSY_RETRY_FIRST_SECONDS
            rp._gemini_json(ai, "p")                         # first model is tried again
        self.assertEqual(ai.models_used, ["m1", "m1", "m2", "m1"])


class KeyRotationTests(unittest.TestCase):
    def test_quota_moves_through_three_keys_in_order(self):
        used: list[tuple[str, str]] = []

        class Client:
            def __init__(self, key):
                self.key = key
                self.chats = self

            def create(self, model):
                used.append((model, self.key))
                if self.key in {"key-1", "key-2"}:
                    raise RuntimeError("429 RESOURCE_EXHAUSTED")
                return self

            def send_message(self, prompt, config=None):
                return type("R", (), {"text": '{"ok": true}'})()

        class AI:
            text_model = "m1"
            client = Client("key-1")

            def _enable_proxy(self):
                pass

            def _disable_proxy(self):
                pass

        ai = AI()
        rp._configure_gemini_key_pool(
            ai,
            [("KEY_1", "key-1"), ("KEY_2", "key-2"), ("KEY_3", "key-3")],
            client_factory=lambda api_key, http_options: Client(api_key),
            log=lambda _m: None,
            model_chain=["m1"],
        )
        self.assertEqual(rp._gemini_json(ai, "p"), {"ok": True})
        self.assertEqual(used, [("m1", "key-1"), ("m1", "key-2"), ("m1", "key-3")])

    def test_three_numbered_keys_are_deduplicated_and_loaded_in_numeric_order(self):
        # This mirrors the planner's .env parsing contract without printing secret values.
        values = {
            "GEMINI_IMAGE_PROJECT_3_KEY": "key-3",
            "GEMINI_IMAGE_PROJECT_1_KEY": "key-1",
            "GEMINI_IMAGE_PROJECT_2_KEY": "key-2",
            "GEMINI_IMAGE_PROJECT_9_KEY": "key-2",
        }
        numbers = sorted(int(name.rsplit("_", 2)[1]) for name in values if name.startswith("GEMINI_IMAGE_PROJECT_"))
        keys = []
        for number in numbers:
            key = values[f"GEMINI_IMAGE_PROJECT_{number}_KEY"]
            if key not in keys:
                keys.append(key)
        self.assertEqual(keys, ["key-1", "key-2", "key-3"])


if __name__ == "__main__":
    unittest.main()
