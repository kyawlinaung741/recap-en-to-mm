"""→ Myanmar narrator tool: the removed modes (VoxCPM, pyannote, mm_to_en, other targets) stay out, and the Smart
Sync plan stays V2. Since 2026-10-17 the SOURCE may be any language (test_source_language.py)."""
from __future__ import annotations

import sys
import tempfile
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import core  # noqa: E402
import recap_planner as rp  # noqa: E402


def _unit(uid: int, start: float, end: float, text: str) -> dict:
    return {"id": uid, "speech_start": start, "speech_end": end, "source_text": text,
            "source_transcript_id": uid - 1, "timestamp": f"{rp._fmt_ts(start)} --> {rp._fmt_ts(end)}"}


class OnlyEnglishToMyanmarTests(unittest.TestCase):
    def test_glm_api_uses_bigmodel_bearer_endpoint_and_json_mode(self):
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]
        }
        with mock.patch.object(rp.requests, "post", return_value=fake_response) as post:
            result = rp._glm_chat_json("test-key", "Return JSON", model="glm-4.7-flash")
        self.assertEqual(result, {"ok": True})
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["model"], "glm-4.7-flash")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})

    def test_no_other_language_mode_or_voice_engine_is_left(self):
        for name in ("recap_planner.py", "core.py", "controller.py", "planner_worker.py", "render_worker.py"):
            text = (APP / name).read_text(encoding="utf-8")
            for word in ("INDONESIAN", "HINDI", "THAI", "SPANISH", "Mandarin", "pyannote", "Pyannote",
                         "VoxCPM", "voxcpm", "Colab", "gradio", "mm_to_en", "include_dialogue"):
                self.assertNotIn(word, text, f"{word} in {name}")

    def test_translation_prompt_is_english_to_burmese(self):
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return {"items": [{"id": 1, "translation": "သူ အိမ်ပြန်လာခဲ့တယ်။"}]}

        with mock.patch.object(rp, "_gemini_json", answer):
            out = rp.translate_batch(None, story_context={}, previous_context=[], current=[_unit(1, 0.0, 2.0, "He came home.")],
                                     next_context=[], log=lambda _m: None)
        self.assertEqual(out[0]["translation"], "သူ အိမ်ပြန်လာခဲ့တယ်။")
        self.assertIn("BURMESE NARRATION TRANSLATOR", prompts[0])
        self.assertIn("Translate ONLY the CURRENT source items", prompts[0])
        self.assertIn("movie/story narrator", prompts[0])
        self.assertIn("A အဆင့် → အေ အဆင့်", prompts[0])
        self.assertIn("stable phonetic name dictionary", prompts[0])

    def test_name_glossary_keeps_first_canonical_spelling(self):
        merged = rp._merge_name_glossary(
            [{"source_name": "Christopher", "burmese_name": "ခရစ်စတိုဖာ"}],
            [{"source_name": "Christopher", "burmese_name": "ခရစ္စတိုဖာ"},
             {"source_name": "Alice", "burmese_name": "အဲလစ်"}],
        )
        self.assertEqual(
            merged,
            [{"source_name": "Christopher", "burmese_name": "ခရစ်စတိုဖာ"},
             {"source_name": "Alice", "burmese_name": "အဲလစ်"}],
        )

    def test_wrong_character_name_is_reasked_until_canonical(self):
        answers = [
            {"items": [{"id": 1, "translation": "ခရစ္စတိုဖာ အိမ်ကို ဝင်လာတယ်။"}]},
            {"items": [{"id": 1, "translation": "ခရစ်စတိုဖာ အိမ်ကို ဝင်လာတယ်။"}]},
        ]
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return answers[len(prompts) - 1]

        with mock.patch.object(rp, "_gemini_json", answer):
            out = rp.translate_batch(
                None,
                story_context={"name_glossary": [
                    {"source_name": "Christopher", "burmese_name": "ခရစ်စတိုဖာ"}
                ]},
                previous_context=[],
                current=[_unit(1, 0.0, 2.0, "Christopher enters the house.")],
                next_context=[],
                log=lambda _m: None,
            )
        self.assertEqual(len(prompts), 2)
        self.assertIn("MANDATORY CANONICAL NAME GLOSSARY", prompts[0])
        self.assertEqual(out[0]["translation"], "ခရစ်စတိုဖာ အိမ်ကို ဝင်လာတယ်။")

    def test_english_words_are_reasked_and_never_returned(self):
        answers = [
            {"items": [{"id": 1, "translation": "ဧည့်ခန်းထဲမှာ မီးခိုးတွေရှိတယ်။ living room"}]},
            {"items": [{"id": 1, "translation": "ဧည့်ခန်းထဲမှာ မီးခိုးတွေရှိတယ်။ smoke"}]},
            {"items": [{"id": 1, "translation": "ဧည့်ခန်းထဲမှာ မီးခိုးတွေရှိတယ်။ room"}]},
            {"items": [{"id": 1, "translation": "ဧည့်ခန်းထဲမှာ မီးခိုးတွေရှိတယ်။"}]},
        ]
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return answers[len(prompts) - 1]

        with mock.patch.object(rp, "_gemini_json", answer):
            out = rp.translate_batch(
                None, story_context={}, previous_context=[],
                current=[_unit(1, 0.0, 2.0, "The living room was full of smoke.")],
                next_context=[], log=lambda _m: None,
            )
        self.assertEqual(len(prompts), 4)
        self.assertEqual(out[0]["translation"], "ဧည့်ခန်းထဲမှာ မီးခိုးတွေရှိတယ်။")
        self.assertEqual(rp._latin_words(out[0]["translation"]), [])

    def test_letters_of_another_script_are_asked_again(self):
        answers = [{"items": [{"id": 1, "translation": "მისခန်းထဲမှာ မီးခိုးတွေ"}]},
                   {"items": [{"id": 1, "translation": "ဧည့်ခန်းထဲမှာ မီးခိုးတွေ"}]}]
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return answers[len(prompts) - 1]

        with mock.patch.object(rp, "_gemini_json", answer):
            out = rp.translate_batch(None, story_context={}, previous_context=[],
                                     current=[_unit(1, 0.0, 2.0, "The living room was full of smoke.")],
                                     next_context=[], log=lambda _m: None)
        self.assertEqual(out[0]["translation"], "ဧည့်ခန်းထဲမှာ မီးခိုးတွေ")
        self.assertIn("letters of another script", prompts[1])
        self.assertEqual(rp._foreign_letters("ဧည့်ခန်း (living room)"), [])

    def test_foreign_script_is_never_silently_stripped_after_retries(self):
        prompts = []

        def answer(_ai, prompt, **_kw):
            prompts.append(prompt)
            return {"items": [{"id": 1, "translation": "მისခန်းထဲမှာ မီးခိုးတွေ"}]}

        with mock.patch.object(rp, "_gemini_json", answer):
            with self.assertRaisesRegex(RuntimeError, "could not be validated"):
                rp.translate_batch(
                    None, story_context={}, previous_context=[],
                    current=[_unit(1, 0.0, 2.0, "The living room was full of smoke.")],
                    next_context=[], log=lambda _m: None,
                )
        self.assertEqual(len(prompts), 4)

    def test_spoken_text_normalization_converts_numbers_percent_and_ampersand(self):
        self.assertEqual(
            rp._normalize_spoken_burmese("၂၀၂၅"), "နှစ်ထောင် နှစ်ဆယ့်ငါး"
        )
        self.assertEqual(
            rp._normalize_spoken_burmese("2025 ခုနှစ်မှာ 50% အောင်မြင်ပြီး အရည်အသွေး & မြန်နှုန်း"),
            "နှစ်ထောင် နှစ်ဆယ့်ငါး ခုနှစ်မှာ ငါးဆယ် ရာခိုင်နှုန်း အောင်မြင်ပြီး အရည်အသွေး နှင့် မြန်နှုန်း",
        )

    def test_plan_covers_the_whole_video_with_midpoint_boundaries(self):
        units = [dict(_unit(1, 1.0, 3.0, "One."), translation="တစ်။"),
                 dict(_unit(2, 5.0, 7.0, "Two."), translation="နှစ်။")]
        plan = rp.make_translation_plan(units, 10.0, source_title="t", transcript={}, story_context={})
        windows = [(s["video_start"], s["video_end"]) for s in plan["segments"]]
        self.assertEqual(windows, [(0.0, 4.0), (4.0, 10.0)])

    def test_smart_sync_caps_the_speed_then_trims(self):
        _vf, fast = core._sync_filter(10.0, 4.0, max_video_speed=1.25)
        self.assertAlmostEqual(fast["applied_factor"], 0.8)
        _vf, slow = core._sync_filter(2.0, 3.0, max_video_speed=1.25)
        self.assertAlmostEqual(slow["applied_factor"], 1.5)


    def test_glm_is_used_after_gemini_fallback_exhaustion_with_same_prompt(self):
        logs = []
        gemini_prompts = []
        glm_prompts = []

        def gemini_failure(_ai, prompt, **_kwargs):
            gemini_prompts.append(prompt)
            raise rp.GeminiKeyPoolExhaustedError("quota exhausted")

        def glm_answer(_key, prompt, **_kwargs):
            glm_prompts.append(prompt)
            return {"items": [{"id": 1, "translation": "သူ အိမ်ပြန်လာတယ်။"}]}

        with mock.patch.object(rp, "_gemini_json", side_effect=gemini_failure):
            with mock.patch.object(rp, "_glm_chat_json", side_effect=glm_answer) as glm:
                out = rp.translate_batch(
                    None, story_context={}, previous_context=[],
                    current=[_unit(1, 0.0, 2.0, "He came home.")],
                    next_context=[], log=logs.append,
                    glm_api_key="test-key", glm_model="glm-4.7-flash",
                )
        self.assertEqual(out[0]["translation"], "သူ အိမ်ပြန်လာတယ်။")
        glm.assert_called_once()
        self.assertEqual(glm_prompts[0], gemini_prompts[0])
        self.assertTrue(any("trying GLM fallback" in line for line in logs))

    def test_glm_builds_story_context_and_keeps_chinese_pinyin(self):
        response = {
            "characters": ["陈阳 is the main character"],
            "relationships": ["陈阳 is 林安羽's friend"],
            "places": ["红星饭店"],
            "terms": [],
            "plot_state": ["陈阳 arrives at the restaurant"],
            "name_consistency": [],
            "name_glossary": [
                {"source_name": "陈阳", "pinyin": "Chén Yáng", "burmese_name": "ချန်ယမ်"}
            ],
            "unresolved": [],
        }
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / "story_context_checkpoint.json"
            with mock.patch.object(rp, "_glm_chat_json", return_value=response) as glm:
                context = rp.build_story_context(
                    None, [_unit(1, 0.0, 2.0, "陈阳来到红星饭店。")],
                    batch_max_items=10, log=lambda _m: None,
                    should_stop=lambda: False, checkpoint_path=checkpoint,
                    source_fingerprint="test-fingerprint", reuse=False,
                    glm_api_key="test-key", glm_model="glm-4.7-flash",
                    source_language="Chinese",
                )
        self.assertEqual(context["name_glossary"][0]["pinyin"], "Chén Yáng")
        self.assertEqual(context["name_glossary"][0]["burmese_name"], "ချန်ယမ်")
        self.assertTrue(checkpoint.is_file())
        self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8"))["version"], 4)
        glm.assert_called_once()



    def test_gemini_builds_story_context_when_glm_fails(self):
        response = {
            "characters": ["陈阳 is the main character"],
            "relationships": [],
            "places": ["红星饭店"],
            "terms": [],
            "plot_state": [],
            "name_consistency": [],
            "name_glossary": [
                {"source_name": "陈阳", "pinyin": "Chén Yáng", "burmese_name": "ချန်ယမ်"}
            ],
            "unresolved": [],
        }
        glm_prompts = []
        gemini_prompts = []

        def glm_failure(_key, prompt, **_kwargs):
            glm_prompts.append(prompt)
            raise RuntimeError("GLM API unavailable")

        def gemini_answer(_ai, prompt, **_kwargs):
            gemini_prompts.append(prompt)
            return response

        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / "story_context_checkpoint.json"
            with mock.patch.object(rp.time, "sleep"):
                with mock.patch.object(rp, "_glm_chat_json", side_effect=glm_failure):
                    with mock.patch.object(rp, "_gemini_json", side_effect=gemini_answer):
                        context = rp.build_story_context(
                            None, [_unit(1, 0.0, 2.0, "陈阳来到红星饭店。")],
                            batch_max_items=10, log=lambda _m: None,
                            should_stop=lambda: False, checkpoint_path=checkpoint,
                            source_fingerprint="gemini-fallback-test", reuse=False,
                            glm_api_key="test-key", glm_model="glm-4.7-flash",
                            source_language="Chinese",
                        )
        self.assertEqual(context["name_glossary"][0]["burmese_name"], "ချန်ယမ်")
        self.assertEqual(len(glm_prompts), 3)
        self.assertEqual(len(gemini_prompts), 1)
        self.assertEqual(gemini_prompts[0], glm_prompts[-1])
        self.assertTrue(checkpoint.is_file())

    def test_glm_fallback_also_covers_sentence_lock_audit(self):
        rows = [dict(_unit(1, 0.0, 2.0, "He came home."), translation="သူ အိမ်ပြန်လာတယ်။")]
        with mock.patch.object(rp, "_gemini_json", side_effect=rp.GeminiKeyPoolExhaustedError("quota")):
            with mock.patch.object(rp, "_glm_chat_json", return_value={
                "checks": [{"id": 1, "status": "pass"}]
            }) as glm:
                audited = rp.audit_and_repair_batch(
                    None, rows, story_context={}, previous_context=[], next_context=[],
                    log=lambda _m: None, glm_api_key="test-key", glm_model="glm-4.7-flash",
                )
        self.assertEqual(audited[0]["translation"], "သူ အိမ်ပြန်လာတယ်။")
        glm.assert_called_once()



if __name__ == "__main__":
    unittest.main()
