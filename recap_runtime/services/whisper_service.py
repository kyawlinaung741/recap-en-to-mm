from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

# The Whisper model download goes through plain HTTP into the Hugging Face cache, so its size
# can be shown while it downloads (the newer "xet" transfer gave no visible progress; same speed).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


class NoUsableSpeechError(RuntimeError):
    """Source downloaded correctly, but Recap cannot obtain usable speech."""


class WhisperTimestampService:
    """
    Local Whisper timestamp engine.

    Preferred backend: faster-whisper (fast, low VRAM, accurate segment/word timestamps)
    Optional Chinese backend: FunASR Paraformer-zh with VAD/punctuation
    Fallback backend: openai-whisper

    Gemini never invents timestamps in V4. This service is the local timing source of truth.
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        fallback_model_size: Optional[str] = None,
        backend: str = "auto",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        self.model_size = model_size or os.getenv("WHISPER_MODEL", "medium")
        self.fallback_model_size = fallback_model_size or os.getenv("WHISPER_MODEL_OTHER", "medium")
        self.backend = (backend or os.getenv("WHISPER_BACKEND", "auto")).lower()
        self.device = device or os.getenv("WHISPER_DEVICE", "cuda")
        self.compute_type = compute_type or os.getenv("WHISPER_COMPUTE_TYPE", "int8_float32")
        self.language = language or os.getenv("WHISPER_LANGUAGE") or None
        self._model: Any = None
        self._active_backend: Optional[str] = None

    def _load_paraformer(self) -> bool:
        """Load FunASR's Chinese-only Paraformer pipeline on demand."""
        try:
            from funasr import AutoModel
        except Exception as exc:
            print(f"⚠️ FunASR is not installed; Paraformer-zh cannot start: {exc}")
            return False
        try:
            print("🧠 Loading Paraformer-zh: ASR + FSMN-VAD + CT-Punc", flush=True)
            kwargs = {
                "model": "paraformer-zh",
                "hub": "ms",
                "vad_model": "fsmn-vad",
                "punc_model": "ct-punc",
                "device": self.device,
            }
            self._model = AutoModel(**kwargs)
            self._active_backend = "paraformer-zh"
            return True
        except Exception as exc:
            print(f"⚠️ Paraformer-zh {self.device} load failed: {exc}")
            print("↩️ Paraformer-zh unavailable; falling back to faster-whisper on the configured device", flush=True)
            return False

    def _download_model_once(self) -> None:
        """First run on a PC: the model (~460 MB for small.en, ~1.5 GB for medium) comes from huggingface.co.

        faster-whisper downloads it with its progress bar switched off, so the log looked frozen
        after "You are sending unauthenticated requests to the HF Hub" (only a warning: no
        account or HF_TOKEN is needed). The downloaded size is printed every 5 seconds instead.
        """
        try:
            from faster_whisper.utils import _MODELS, download_model
        except Exception:
            return
        repo = _MODELS.get(str(self.model_size))
        if not repo:
            return  # a local folder or another repo id: faster-whisper handles it
        try:
            download_model(str(self.model_size), local_files_only=True)
            return  # already on this PC
        except Exception:
            pass
        import threading

        from huggingface_hub import constants

        folder = Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))
        size = {"tiny": 75, "base": 145, "small": 465, "small.en": 465, "medium": 1530}.get(str(self.model_size))
        print(
            f"⬇️ First run only: downloading the Whisper model '{self.model_size}'"
            + (f" (~{size} MB)" if size else "") + " from huggingface.co. "
            "No account is needed — the HF_TOKEN warning can be ignored.",
            flush=True,
        )
        done = threading.Event()

        def report() -> None:
            while not done.wait(5.0):
                files = (folder / "blobs") if (folder / "blobs").is_dir() else folder
                size = sum(f.stat().st_size for f in files.rglob("*") if f.is_file()) if files.is_dir() else 0
                print(f"⬇️ Whisper model: {size / 1_000_000:.0f} MB downloaded...", flush=True)

        threading.Thread(target=report, daemon=True).start()
        try:
            for attempt in range(1, 4):  # a dropped connection is tried again; the download resumes
                try:
                    download_model(str(self.model_size))
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise RuntimeError(
                            f"Could not download the Whisper model from huggingface.co "
                            f"({' '.join(str(exc).split())[:200]}). Check the internet. If huggingface.co does not "
                            "open on this PC, use a VPN, or put HF_ENDPOINT=https://hf-mirror.com in the .env file "
                            "and start again."
                        ) from exc
                    print(f"⚠️ Whisper model download interrupted ({' '.join(str(exc).split())[:120]}); "
                          f"trying again {attempt + 1}/3...", flush=True)
                    time.sleep(5 * attempt)
        finally:
            done.set()
        print("✅ Whisper model downloaded (kept on this PC for next time)", flush=True)

    def _load_faster_whisper(self) -> bool:
        try:
            from faster_whisper import WhisperModel
        except Exception:
            return False

        self._download_model_once()
        # Try the configured type first. If this GPU/backend rejects it (for example,
        # GTX 10-series does not efficiently support float16 in CTranslate2), try only
        # compute types reported as supported by CTranslate2 before falling back to CPU.
        tried_types: set[str] = set()
        gpu_types: list[str] = [self.compute_type]
        if self.device != "cpu":
            try:
                import ctranslate2
                supported = ctranslate2.get_supported_compute_types(self.device, 0)
                for candidate in ("int8_float32", "int8", "float32"):
                    if candidate in supported and candidate not in gpu_types:
                        gpu_types.append(candidate)
            except Exception as probe_exc:
                print(f"⚠️ Could not query GPU compute types: {probe_exc}")

        last_gpu_exc: Optional[Exception] = None
        for compute_type in gpu_types:
            if compute_type in tried_types:
                continue
            tried_types.add(compute_type)
            try:
                print(
                    f"🧠 Loading faster-whisper: model={self.model_size}, "
                    f"device={self.device}, compute={compute_type}"
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=compute_type,
                )
                self._active_backend = "faster-whisper"
                self.compute_type = compute_type
                if compute_type != gpu_types[0]:
                    print(f"✅ GPU fallback selected compute_type={compute_type}")
                return True
            except Exception as exc:
                last_gpu_exc = exc
                print(f"⚠️ faster-whisper load failed (device={self.device}, compute={compute_type}): {exc}")

        if self.device != "cpu":
            try:
                print("↩️ All available GPU compute types failed; trying CPU fallback (int8)")
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                self._active_backend = "faster-whisper"
                self.device = "cpu"
                self.compute_type = "int8"
                print("✅ faster-whisper CPU fallback loaded")
                return True
            except Exception as cpu_exc:
                print(f"⚠️ faster-whisper CPU fallback failed: {cpu_exc}")
        elif last_gpu_exc is not None:
            print(f"⚠️ faster-whisper CPU load failed: {last_gpu_exc}")
        return False

    def _load_openai_whisper(self) -> bool:
        try:
            import whisper
        except Exception:
            return False

        try:
            print(f"🧠 Loading openai-whisper: model={self.model_size}, device={self.device}")
            self._model = whisper.load_model(self.model_size, device=self.device)
            self._active_backend = "openai-whisper"
            return True
        except Exception as exc:
            print(f"⚠️ openai-whisper GPU load failed: {exc}")
            if self.device != "cpu":
                try:
                    self._model = whisper.load_model(self.model_size, device="cpu")
                    self._active_backend = "openai-whisper"
                    self.device = "cpu"
                    return True
                except Exception as cpu_exc:
                    print(f"⚠️ openai-whisper CPU fallback failed: {cpu_exc}")
            return False

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        backends = []
        if self.backend in {"paraformer", "paraformer-zh", "funasr"}:
            backends.append("paraformer")
        if self.backend in {"auto", "faster", "faster-whisper"}:
            backends.append("faster")
        if self.backend in {"auto", "openai", "openai-whisper", "whisper"}:
            backends.append("openai")

        for backend in backends:
            if backend == "paraformer" and self._load_paraformer():
                return
            if backend == "paraformer":
                self.model_size = str(self.fallback_model_size or "medium").strip() or "medium"
                if self._load_faster_whisper():
                    return
            if backend == "faster" and self._load_faster_whisper():
                return
            if backend == "openai" and self._load_openai_whisper():
                return

        raise RuntimeError(
            "Local ASR backend မတွေ့ပါ။ Paraformer-zh, faster-whisper သို့မဟုတ် openai-whisper "
            "install/config ကိုစစ်ပါ။"
        )

    def detect_language(self, media_path: str) -> tuple[str, float]:
        """Which language the speech in media_path is in: (Whisper code such as "en", "zh", "hi", probability).
        Needs a multilingual model (not a ".en" one); music and silence are skipped (VAD), up to 8 pieces of 30 s."""
        self._ensure_model()
        if self._active_backend != "faster-whisper":
            raise RuntimeError("Language detection needs faster-whisper")
        from faster_whisper import decode_audio

        audio = decode_audio(str(media_path), sampling_rate=16000)
        try:
            language, probability, _all = self._model.detect_language(
                audio=audio, vad_filter=True, language_detection_segments=8)
        except RuntimeError as exc:
            text = str(exc).lower()
            if self.device == "cpu" or not any(word in text for word in ("cublas", "cudnn", "cuda", ".dll")):
                raise
            print(f"⚠️ GPU Whisper failed ({exc}); using the CPU instead")
            self._model = None
            self.device, self.compute_type = "cpu", "int8"
            self._ensure_model()
            language, probability, _all = self._model.detect_language(
                audio=audio, vad_filter=True, language_detection_segments=8)
        return str(language), float(probability)

    @staticmethod
    def _clean_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _fmt_clock(seconds: float) -> str:
        seconds = max(0, int(seconds or 0))
        h, rem = divmod(seconds, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _transcribe_faster(self, media_path: str, vad_filter: bool = True, media_duration: Optional[float] = None) -> dict[str, Any]:
        # FAST-SYNC profile: keep word timestamps, but avoid expensive beam search.
        # Language is supplied by the planner: English uses small.en/en, other languages the multilingual model.
        kwargs: dict[str, Any] = {
            "beam_size": 1,
            "best_of": 1,
            "vad_filter": bool(vad_filter),
            "word_timestamps": True,
            "condition_on_previous_text": False,
            "temperature": 0.0,
        }
        if self.language:
            kwargs["language"] = self.language
        if not str(self.model_size).endswith(".en"):
            # Other languages (2026-10-17): the multilingual medium model on a Hindi recap wrote "ॉॉॉॉ…" and
            # "पर पाइजावाद पर पाइजावाद …" over real speech (3 loops in 2 min). With beam search and Whisper's
            # temperature fallback (a piece that loops is decoded again) the loops were gone, 36% more speech came
            # back and the sentence marks (।) were written; English keeps the fast settings above.
            kwargs["beam_size"] = 5
            kwargs["temperature"] = (0.0, 0.2, 0.4, 0.6, 0.8)

        segments_iter, info = self._model.transcribe(media_path, **kwargs)
        segments: list[dict[str, Any]] = []
        words_total = 0
        avg_logprob_values: list[float] = []
        no_speech_values: list[float] = []
        compression_ratio_values: list[float] = []
        next_progress = 5
        total_duration = float(media_duration or 0.0)
        for idx, seg in enumerate(segments_iter):
            text = self._clean_text(getattr(seg, "text", ""))
            start = float(getattr(seg, "start", 0.0) or 0.0)
            end = float(getattr(seg, "end", 0.0) or 0.0)
            if total_duration > 0 and end > 0:
                pct = min(99, int((end / total_duration) * 100))
                if pct >= next_progress:
                    print(
                        f"⏳ Whisper {pct:02d}% | "
                        f"{self._fmt_clock(end)} / {self._fmt_clock(total_duration)}",
                        flush=True,
                    )
                    next_progress = ((pct // 5) + 1) * 5
            if not text or end <= start:
                continue
            words = []
            for word in getattr(seg, "words", None) or []:
                w_text = self._clean_text(getattr(word, "word", ""))
                w_start = float(getattr(word, "start", start) or start)
                w_end = float(getattr(word, "end", w_start) or w_start)
                if not w_text or w_end <= w_start:
                    continue
                words.append({
                    "start": round(w_start, 3),
                    "end": round(w_end, 3),
                    "text": w_text,
                })
            words_total += len(words)

            avg_logprob = getattr(seg, "avg_logprob", None)
            no_speech_prob = getattr(seg, "no_speech_prob", None)
            compression_ratio = getattr(seg, "compression_ratio", None)
            try:
                if avg_logprob is not None:
                    avg_logprob_values.append(float(avg_logprob))
            except Exception:
                pass
            try:
                if no_speech_prob is not None:
                    no_speech_values.append(float(no_speech_prob))
            except Exception:
                pass
            try:
                if compression_ratio is not None:
                    compression_ratio_values.append(float(compression_ratio))
            except Exception:
                pass

            segments.append({
                "id": len(segments),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "words": words,
            })

        return {
            "backend": "faster-whisper",
            "model": self.model_size,
            "language": getattr(info, "language", self.language or "") or "",
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
            "segments": segments,
            "word_count": words_total,
            "avg_logprob": (sum(avg_logprob_values) / len(avg_logprob_values)) if avg_logprob_values else None,
            "avg_no_speech_prob": (sum(no_speech_values) / len(no_speech_values)) if no_speech_values else None,
            "avg_compression_ratio": (sum(compression_ratio_values) / len(compression_ratio_values)) if compression_ratio_values else None,
        }

    def _transcribe_faster_chunked(self, media_path: str, vad_filter: bool = True, media_duration: Optional[float] = None) -> dict[str, Any]:
        """Split long sources into bounded PCM chunks before faster-whisper feature extraction."""
        chunk_seconds = max(60, int(os.getenv("WHISPER_CHUNK_SECONDS", "300")))
        threshold = max(chunk_seconds, int(os.getenv("WHISPER_CHUNK_THRESHOLD_SECONDS", "600")))
        duration = float(media_duration or 0.0)
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if duration <= 0 and ffprobe:
            probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", media_path], capture_output=True, text=True, timeout=30)
            try: duration = float((probe.stdout or "").strip()) if probe.returncode == 0 else 0.0
            except (TypeError, ValueError): duration = 0.0
        if duration <= threshold:
            return self._transcribe_faster(media_path, vad_filter=vad_filter, media_duration=media_duration)
        if not ffmpeg:
            raise RuntimeError("Long-audio Whisper needs ffmpeg on PATH to split the source safely; no whole-file fallback was attempted because it may exhaust RAM.")

        print(f"🧩 Long-audio mode: splitting {self._fmt_clock(duration)} into {chunk_seconds}s chunks", flush=True)
        all_segments, logprobs, no_speech, compression = [], [], [], []
        words_total, language, language_probability, vad_fallback_used = 0, self.language or "", 0.0, False
        with tempfile.TemporaryDirectory(prefix="recap-whisper-") as td:
            pattern = str(Path(td) / "chunk_%05d.wav")
            split = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", media_path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1", pattern], capture_output=True, text=True, timeout=max(300, int(duration * 0.25)))
            if split.returncode:
                raise RuntimeError("FFmpeg could not split long Whisper audio: " + (split.stderr or "")[-1000:])
            chunks = sorted(Path(td).glob("chunk_*.wav"))
            if not chunks: raise RuntimeError("FFmpeg produced no audio chunks for Whisper.")
            for i, chunk in enumerate(chunks):
                offset = i * chunk_seconds
                print(f"🎙️ Whisper chunk {i+1}/{len(chunks)} | {self._fmt_clock(offset)}", flush=True)
                part = self._transcribe_faster(str(chunk), vad_filter=vad_filter)
                if not part.get("segments") and vad_filter:
                    print(f"⚠️ Chunk {i+1}: retrying with VAD=OFF", flush=True)
                    part = self._transcribe_faster(str(chunk), vad_filter=False)
                    vad_fallback_used = vad_fallback_used or bool(part.get("segments"))
                if not language:
                    language = str(part.get("language") or "")
                    language_probability = float(part.get("language_probability") or 0.0)
                for raw in part.get("segments") or []:
                    seg = dict(raw); seg["id"] = len(all_segments)
                    seg["start"] = round(float(seg.get("start", 0)) + offset, 3)
                    seg["end"] = round(float(seg.get("end", 0)) + offset, 3)
                    seg["words"] = [{**w, "start": round(float(w.get("start", 0)) + offset, 3), "end": round(float(w.get("end", 0)) + offset, 3)} for w in (seg.get("words") or [])]
                    all_segments.append(seg)
                words_total += int(part.get("word_count") or 0)
                for key, dest in (("avg_logprob", logprobs), ("avg_no_speech_prob", no_speech), ("avg_compression_ratio", compression)):
                    try:
                        if part.get(key) is not None: dest.append(float(part[key]))
                    except (TypeError, ValueError): pass
        result = {"backend":"faster-whisper", "model":self.model_size, "language":language, "language_probability":language_probability, "segments":all_segments, "word_count":words_total,
                  "avg_logprob":sum(logprobs)/len(logprobs) if logprobs else None,
                  "avg_no_speech_prob":sum(no_speech)/len(no_speech) if no_speech else None,
                  "avg_compression_ratio":sum(compression)/len(compression) if compression else None}
        if vad_fallback_used: result["vad_fallback_used"] = True
        print(f"✅ Long-audio chunks combined: {len(all_segments)} segments", flush=True)
        return result

    @staticmethod
    def _paraformer_seconds(value: Any) -> float:
        """FunASR sentence_info timestamps are milliseconds; tolerate seconds too."""
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return number / 1000.0 if number > 100.0 else number

    def _transcribe_paraformer(self, media_path: str, media_duration: Optional[float] = None) -> dict[str, Any]:
        batch_size_s = max(30, int(os.getenv("PARAFORMER_BATCH_SIZE_S", "300")))
        raw_result = self._model.generate(input=media_path, batch_size_s=batch_size_s)
        raw = raw_result[0] if isinstance(raw_result, list) and raw_result else raw_result
        raw = raw if isinstance(raw, dict) else {}
        segments: list[dict[str, Any]] = []
        for item in raw.get("sentence_info") or raw.get("sentences") or []:
            if not isinstance(item, dict):
                continue
            text = self._clean_text(item.get("text") or item.get("sentence") or "")
            start = self._paraformer_seconds(item.get("start"))
            end = self._paraformer_seconds(item.get("end"))
            if text and end > start:
                segments.append({
                    "id": len(segments),
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                    "words": [],
                })
        if not segments:
            text = self._clean_text(raw.get("text") or "")
            if text:
                end = float(media_duration or 0.0)
                if end <= 0:
                    end = 1.0
                segments.append({"id": 0, "start": 0.0, "end": round(end, 3), "text": text, "words": []})
        return {
            "backend": "paraformer-zh",
            "model": "paraformer-zh",
            "language": "zh",
            "language_probability": 1.0,
            "segments": segments,
            "word_count": sum(len(str(seg["text"]).split()) for seg in segments),
        }

    def _transcribe_openai(self, media_path: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "verbose": False,
            "word_timestamps": True,
            "fp16": self.device != "cpu",
        }
        if self.language:
            kwargs["language"] = self.language
        result = self._model.transcribe(media_path, **kwargs)

        segments: list[dict[str, Any]] = []
        words_total = 0
        for raw in result.get("segments") or []:
            text = self._clean_text(raw.get("text", ""))
            start = float(raw.get("start", 0.0) or 0.0)
            end = float(raw.get("end", 0.0) or 0.0)
            if not text or end <= start:
                continue
            words = []
            for word in raw.get("words") or []:
                w_text = self._clean_text(word.get("word", ""))
                w_start = float(word.get("start", start) or start)
                w_end = float(word.get("end", w_start) or w_start)
                if not w_text or w_end <= w_start:
                    continue
                words.append({
                    "start": round(w_start, 3),
                    "end": round(w_end, 3),
                    "text": w_text,
                })
            words_total += len(words)
            segments.append({
                "id": len(segments),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "words": words,
            })

        return {
            "backend": "openai-whisper",
            "model": self.model_size,
            "language": result.get("language") or self.language or "",
            "language_probability": None,
            "segments": segments,
            "word_count": words_total,
        }

    @staticmethod
    def _probe_audio_stream(media_path: str) -> Optional[bool]:
        """Return True/False when ffprobe is available, otherwise None."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    media_path,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return bool((result.stdout or "").strip())


    @staticmethod
    def _assess_vad_fallback_quality(result: dict[str, Any]) -> dict[str, Any]:
        """Conservatively decide whether a VAD-OFF rescue looks like real speech.

        This guard runs ONLY after VAD=ON returned zero segments. In that state,
        tiny/repetitive VAD-OFF transcripts are commonly music/noise hallucinations.
        """
        segments = result.get("segments") or []
        transcript = " ".join(str(seg.get("text") or "") for seg in segments).strip()
        tokens = [
            token.strip(".,!?;:'\"()[]{}<>-_—–…").lower()
            for token in transcript.split()
        ]
        tokens = [token for token in tokens if token]
        meaningful = [token for token in tokens if any(ch.isalnum() for ch in token)]
        unique_ratio = (len(set(meaningful)) / len(meaningful)) if meaningful else 0.0

        spoken_seconds = 0.0
        for seg in segments:
            try:
                start = float(seg.get("start", 0.0) or 0.0)
                end = float(seg.get("end", 0.0) or 0.0)
                if end > start:
                    spoken_seconds += end - start
            except Exception:
                pass

        media_duration = float(result.get("media_duration") or 0.0)
        coverage = (spoken_seconds / media_duration) if media_duration > 0 else None
        language_probability = result.get("language_probability")
        try:
            language_probability = float(language_probability) if language_probability is not None else None
        except Exception:
            language_probability = None

        avg_logprob = result.get("avg_logprob")
        avg_no_speech_prob = result.get("avg_no_speech_prob")
        try:
            avg_logprob = float(avg_logprob) if avg_logprob is not None else None
        except Exception:
            avg_logprob = None
        try:
            avg_no_speech_prob = float(avg_no_speech_prob) if avg_no_speech_prob is not None else None
        except Exception:
            avg_no_speech_prob = None

        reasons: list[str] = []
        min_words = max(4, int(os.getenv("WHISPER_FALLBACK_MIN_WORDS", "10")))
        min_spoken_seconds = max(1.0, float(os.getenv("WHISPER_FALLBACK_MIN_SPEECH_SECONDS", "5.0")))
        min_unique_ratio = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MIN_UNIQUE_RATIO", "0.42"))))
        min_language_probability = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MIN_LANGUAGE_PROB", "0.35"))))
        min_coverage = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MIN_COVERAGE", "0.08"))))
        max_no_speech_prob = min(1.0, max(0.0, float(os.getenv("WHISPER_FALLBACK_MAX_NO_SPEECH_PROB", "0.65"))))
        min_avg_logprob = float(os.getenv("WHISPER_FALLBACK_MIN_AVG_LOGPROB", "-1.20"))

        if len(meaningful) < min_words:
            reasons.append(f"too_few_words={len(meaningful)}<{min_words}")
        if spoken_seconds < min_spoken_seconds:
            reasons.append(f"speech_seconds={spoken_seconds:.2f}<{min_spoken_seconds:.2f}")
        if len(meaningful) >= 6 and unique_ratio < min_unique_ratio:
            reasons.append(f"repetitive_unique_ratio={unique_ratio:.2f}<{min_unique_ratio:.2f}")
        if language_probability is not None and language_probability > 0 and language_probability < min_language_probability:
            reasons.append(f"language_probability={language_probability:.2f}<{min_language_probability:.2f}")
        if coverage is not None and media_duration >= 20.0 and coverage < min_coverage:
            reasons.append(f"speech_coverage={coverage:.2f}<{min_coverage:.2f}")
        if avg_no_speech_prob is not None and avg_no_speech_prob > max_no_speech_prob:
            reasons.append(f"avg_no_speech={avg_no_speech_prob:.2f}>{max_no_speech_prob:.2f}")
        if avg_logprob is not None and avg_logprob < min_avg_logprob:
            reasons.append(f"avg_logprob={avg_logprob:.2f}<{min_avg_logprob:.2f}")

        return {
            "usable": not reasons,
            "reasons": reasons,
            "word_count": len(meaningful),
            "spoken_seconds": round(spoken_seconds, 3),
            "speech_coverage": round(coverage, 4) if coverage is not None else None,
            "unique_ratio": round(unique_ratio, 4),
            "language_probability": language_probability,
            "avg_logprob": avg_logprob,
            "avg_no_speech_prob": avg_no_speech_prob,
        }

    def transcribe(self, media_path: str, media_duration: Optional[float] = None) -> dict[str, Any]:
        path = Path(media_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Whisper input မတွေ့ပါ: {path}")

        audio_probe = self._probe_audio_stream(str(path))
        if audio_probe is False:
            raise NoUsableSpeechError("NO_USABLE_SPEECH: ffprobe found no audio stream in source media.")

        self._ensure_model()
        print(f"🎙️ Local Whisper timestamp transcription: {path.name}")

        if self._active_backend == "paraformer-zh":
            result = self._transcribe_paraformer(str(path), media_duration=media_duration)
        elif self._active_backend == "faster-whisper":
            try:
                result = self._transcribe_faster_chunked(str(path), vad_filter=True, media_duration=media_duration)
            except RuntimeError as exc:
                # An NVIDIA GPU without the CUDA 12 libraries (cublas64_12.dll / cuDNN) loads the
                # model but fails on the first audio: finish on the CPU instead of stopping.
                text = str(exc).lower()
                if self.device == "cpu" or not any(word in text for word in ("cublas", "cudnn", "cuda", ".dll")):
                    raise
                print(f"⚠️ GPU Whisper failed ({exc}); using the CPU instead (slower)")
                self._model = None
                self.device, self.compute_type = "cpu", "int8"
                self._ensure_model()
                result = self._transcribe_faster(str(path), vad_filter=True, media_duration=media_duration)
            if not result.get("segments"):
                print("⚠️ Whisper VAD=ON returned 0 segments — retrying SAME source once with VAD=OFF...")
                result = self._transcribe_faster_chunked(str(path), vad_filter=False, media_duration=media_duration)
                result["vad_fallback_used"] = True
        elif self._active_backend == "openai-whisper":
            result = self._transcribe_openai(str(path))
        else:
            raise RuntimeError("Whisper backend မရွေးရသေးပါ။")

        if not result.get("segments"):
            raise NoUsableSpeechError(
                "NO_USABLE_SPEECH: Whisper returned 0 usable transcript segments after fallback."
            )

        if media_duration is not None:
            result["media_duration"] = round(float(media_duration), 3)
        else:
            result["media_duration"] = round(float(result["segments"][-1]["end"]), 3)

        result["text"] = " ".join(seg["text"] for seg in result["segments"]).strip()

        if bool(result.get("vad_fallback_used")):
            quality = self._assess_vad_fallback_quality(result)
            result["vad_fallback_quality"] = quality
            if not bool(quality.get("usable")):
                reasons = ", ".join(quality.get("reasons") or ["low_confidence_fallback_transcript"])
                print(
                    "🎵 VAD-OFF rescue rejected as likely music/noise or too-thin speech → "
                    f"{reasons}"
                )
                raise NoUsableSpeechError(
                    "MUSIC_ONLY_OR_TRANSCRIPT_TOO_THIN: " + reasons
                )
            print(
                "✅ VAD-OFF rescue passed speech-quality guard → "
                f"words={quality.get('word_count')}, "
                f"speech={quality.get('spoken_seconds')}s, "
                f"unique={quality.get('unique_ratio')}"
            )

        print(
            f"✅ Whisper done: {len(result['segments'])} segments, "
            f"language={result.get('language') or 'auto'}"
        )
        return result
