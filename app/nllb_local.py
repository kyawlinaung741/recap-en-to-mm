from __future__ import annotations

import re
from typing import Any, Callable

MODEL_ID = "facebook/nllb-200-distilled-600M"
TARGET_LANGUAGE = "mya_Mymr"

# Whisper language code -> NLLB FLORES-200 language code.
SOURCE_LANGUAGE_CODES = {
    "zh": "zho_Hans", "zh-cn": "zho_Hans", "zh-tw": "zho_Hant",
    "en": "eng_Latn", "hi": "hin_Deva", "ko": "kor_Hang", "ja": "jpn_Jpan",
    "th": "tha_Thai", "vi": "vie_Latn", "id": "ind_Latn", "ms": "zsm_Latn",
    "tl": "tgl_Latn", "es": "spa_Latn", "pt": "por_Latn", "fr": "fra_Latn",
    "de": "deu_Latn", "it": "ita_Latn", "ru": "rus_Cyrl", "tr": "tur_Latn",
    "ar": "arb_Arab", "bn": "ben_Beng", "ta": "tam_Taml", "te": "tel_Telu",
    "ur": "urd_Arab",
}

_MODEL_CACHE: dict[tuple[str, str], tuple[Any, Any, Any]] = {}


def _load_model(source_code: str, log: Callable[[str], None]) -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except Exception as exc:
        raise RuntimeError(
            "NLLB Local လိုအပ်တဲ့ PyTorch / Transformers မရှိပါ။ "
            "INSTALL_REQUIREMENTS.bat ကို run ပြီး NLLB packages ကို install လုပ်ပါ။"
        ) from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_key = (MODEL_ID, device)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    log(f"⬇️ NLLB model loading: {MODEL_ID} (first run downloads about 2.4 GB)")
    log(f"🖥️ NLLB device: {device}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=False)
    dtype = torch.float16 if device == "cuda" else torch.float32
    # Avoid an Accelerate dependency; the distilled 600M checkpoint fits normal loading.
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID, torch_dtype=dtype)
    model.to(device)
    model.eval()
    cached = (tokenizer, model, torch.device(device))
    _MODEL_CACHE[cache_key] = cached
    log("✅ NLLB model ready")
    return cached


class NLLBLocalTranslator:
    """Local NLLB-200 translator. No translation API key or per-character fee."""

    def __init__(
        self,
        source_language: str,
        *,
        log: Callable[[str], None],
        should_stop: Callable[[], bool],
    ):
        raw_code = str(source_language or "").strip().lower()
        self.source_code = SOURCE_LANGUAGE_CODES.get(raw_code)
        if not self.source_code:
            raise RuntimeError(
                f"NLLB Local မှာ source language '{raw_code}' အတွက် mapping မရှိသေးပါ။ "
                "Gemini ကိုရွေးပါ၊ သို့မဟုတ် supported language mapping ထည့်ရန်လိုပါတယ်။"
            )
        self.log = log
        self.should_stop = should_stop
        self.tokenizer, self.model, self.device = _load_model(self.source_code, log)
        self.tokenizer.src_lang = self.source_code
        self.target_token_id = self.tokenizer.convert_tokens_to_ids(TARGET_LANGUAGE)
        if self.target_token_id is None or self.target_token_id < 0:
            raise RuntimeError("NLLB tokenizer ထဲမှာ Burmese target language (mya_Mymr) မတွေ့ပါ။")

    @staticmethod
    def _protect_names(source_text: str, glossary: list[dict[str, str]]) -> tuple[str, dict[str, str]]:
        protected = source_text
        restore: dict[str, str] = {}
        candidates = []
        for entry in glossary or []:
            if not isinstance(entry, dict):
                continue
            source_name = str(entry.get("source_name") or "").strip()
            burmese_name = str(entry.get("burmese_name") or "").strip()
            if len(source_name) >= 2 and burmese_name and source_name in protected:
                candidates.append((source_name, burmese_name))
        # Longest first prevents a shorter name from consuming part of a longer name.
        for index, (source_name, burmese_name) in enumerate(
            sorted(candidates, key=lambda item: len(item[0]), reverse=True), 1
        ):
            token = f"ZXQNAME{index:04d}QXZ"
            if source_name in protected:
                protected = protected.replace(source_name, token)
                restore[token] = burmese_name
        return protected, restore

    def translate_batch(
        self,
        current: list[dict[str, Any]],
        *,
        glossary: list[dict[str, str]],
        batch_size: int = 4,
    ) -> list[dict[str, Any]]:
        import torch

        if not current:
            return []
        prepared: list[tuple[dict[str, Any], str, dict[str, str]]] = []
        for row in current:
            if self.should_stop():
                raise InterruptedError("STOP requested during NLLB translation")
            protected, restore = self._protect_names(
                str(row.get("source_text") or ""), glossary
            )
            prepared.append((row, protected, restore))

        outputs: list[dict[str, Any]] = []
        for offset in range(0, len(prepared), max(1, int(batch_size))):
            if self.should_stop():
                raise InterruptedError("STOP requested during NLLB translation")
            window = prepared[offset:offset + max(1, int(batch_size))]
            texts = [item[1] for item in window]
            encoded = self.tokenizer(
                texts, return_tensors="pt", padding=True, truncation=False
            )
            if int(encoded["input_ids"].shape[1]) > 512:
                raise RuntimeError(
                    "NLLB input တစ် batch မှာ 512 tokens ကျော်နေပါတယ်။ "
                    "ဒီစာကြောင်းကို ပိုတိုတဲ့ timestamp unit အဖြစ် ခွဲပြီး ပြန်စမ်းပါ။"
                )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with torch.inference_mode():
                generated = self.model.generate(
                    **encoded,
                    forced_bos_token_id=self.target_token_id,
                    num_beams=4,
                    max_new_tokens=256,
                    early_stopping=True,
                )
            decoded = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
            if len(decoded) != len(window):
                raise RuntimeError("NLLB returned a different number of translations than source rows.")

            for (source_row, _protected, restore), text in zip(window, decoded):
                translated = str(text or "").strip()
                for token, burmese_name in restore.items():
                    # SentencePiece may insert spaces inside an unfamiliar Latin token.
                    token_pattern = re.compile(r"\s*".join(re.escape(char) for char in token), re.IGNORECASE)
                    if not token_pattern.search(translated):
                        raise RuntimeError(
                            f"NLLB က protected name token ကို မထိန်းနိုင်ပါ။ "
                            f"ID {int(source_row['id']):05d}; name restoration refused."
                        )
                    translated = token_pattern.sub(lambda _match: burmese_name, translated, count=1)
                if not translated:
                    raise RuntimeError(f"NLLB returned an empty translation for ID {int(source_row['id']):05d}.")
                outputs.append({
                    **source_row,
                    "translation": translated,
                })
        return outputs
