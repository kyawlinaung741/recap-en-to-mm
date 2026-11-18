"""Structured per-job error records.

The human-readable ``run.log`` remains the primary console log. This module adds
an append-only ``errors.jsonl`` sidecar so failures can be filtered and resumed
without parsing prose.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()


def classify_error(message: str, *, stage: str = "") -> tuple[str, bool]:
    """Return a stable error type and whether retrying is normally reasonable."""
    text = f"{stage} {message}".lower()
    rules = (
        ("quota", ("quota", "resource_exhausted", "rate limit", "too many requests"), True),
        ("authentication", ("api key", "unauthenticated", "permission denied", "401", "403"), False),
        ("timeout", ("timeout", "timed out", "deadline exceeded"), True),
        ("network", ("connection", "network", "dns", "proxy", "503", "502", "502"), True),
        ("invalid_json", ("json", "decode", "expecting", "malformed"), True),
        ("schema_validation", ("id mismatch", "schema", "validation", "invalid audit"), True),
        ("duplicate_translation", ("same thing", "near-duplicate", "duplicate translation"), True),
        ("ffmpeg", ("ffmpeg", "ffprobe", "nvenc", "encoder"), True),
        ("audio_video_sync", ("audio/video", "audio video", "av sync", "duration drift"), False),
    )
    for error_type, needles, retryable in rules:
        if any(needle in text for needle in needles):
            return error_type, retryable
    if stage.lower().startswith(("tts", "render")):
        return "tts" if stage.lower().startswith("tts") else "render", True
    return "unknown", False


def append_error(
    path: str | Path,
    *,
    stage: str,
    message: str,
    job_id: str = "",
    segment_id: int | None = None,
    role: str = "",
    model: str = "",
    key_index: int | None = None,
    retry_count: int = 0,
    error_type: str | None = None,
    retryable: bool | None = None,
    error_code: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one JSON object and return the normalized record.

    Logging failures are intentionally not raised into the production pipeline.
    Callers may use the returned record for tests or UI diagnostics.
    """
    clean_message = str(message or "").strip() or "Unknown error"
    inferred_type, inferred_retryable = classify_error(clean_message, stage=stage)
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_id": str(job_id or ""),
        "segment_id": int(segment_id) if segment_id is not None else None,
        "stage": str(stage or "unknown"),
        "role": str(role or ""),
        "model": str(model or ""),
        "key_index": int(key_index) if key_index is not None else None,
        "error_type": str(error_type or inferred_type),
        "error_code": str(error_code or ""),
        "message": clean_message[:4000],
        "retryable": inferred_retryable if retryable is None else bool(retryable),
        "retry_count": max(0, int(retry_count or 0)),
    }
    if details:
        record["details"] = details
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _LOCK, target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
    except Exception:
        # Diagnostics must never turn the original application error into a new failure.
        pass
    return record


def error_log_path(job_dir: str | Path) -> Path:
    return Path(job_dir) / "errors.jsonl"
