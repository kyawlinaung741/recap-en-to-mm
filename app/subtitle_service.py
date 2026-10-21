from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


POSITIONS = {
    "Top Left": 7,
    "Top Center": 8,
    "Top Right": 9,
    "Middle Left": 4,
    "Center": 5,
    "Middle Right": 6,
    "Bottom Left": 1,
    "Bottom Center": 2,
    "Bottom Right": 3,
}


def _seconds(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _srt_time(value: float) -> str:
    total_ms = max(0, int(round(_seconds(value) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def subtitle_segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return subtitle rows using the actual concatenated TTS timeline.

    ``tts_timing_segments`` is the master clock. This is deliberately preferred
    over the original video timestamps so subtitles follow the Myanmar voice.
    """
    raw = plan.get("tts_timing_segments") or plan.get("subtitle_segments") or []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = _seconds(item.get("audio_start", item.get("start")))
        end = _seconds(item.get("audio_end", item.get("end")))
        text = str(item.get("text", item.get("narration", "")) or "").strip()
        if text and end > start + 0.01:
            rows.append({"start": start, "end": end, "text": text})
    return rows


def write_srt(plan: dict[str, Any], output: Path) -> Path:
    rows = subtitle_segments(plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    for index, row in enumerate(rows, 1):
        parts.extend([str(index), f"{_srt_time(row['start'])} --> {_srt_time(row['end'])}", row["text"], ""])
    output.write_text("\n".join(parts), encoding="utf-8-sig")
    return output


def _filter_path(path: Path) -> str:
    # FFmpeg filter arguments use ':' and '\\' as separators/escapes.
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def burn_subtitles(
    ffmpeg: str,
    input_video: Path,
    subtitle_file: Path,
    output_video: Path,
    *,
    position: str = "Bottom Center",
    font_size: int = 30,
    margin: int = 42,
    font_name: str = "Myanmar Text",
    primary_colour: str = "&H00FFFFFF",
    outline_colour: str = "&H80000000",
    encoder_args: list[str] | None = None,
) -> Path:
    alignment = POSITIONS.get(position, 2)
    style = (
        f"FontName={font_name},FontSize={max(10, min(int(font_size), 96))},"
        f"PrimaryColour={primary_colour},OutlineColour={outline_colour},"
        f"BorderStyle=1,Outline=2,Shadow=0,Alignment={alignment},"
        f"MarginV={max(0, min(int(margin), 500))}"
    )
    vf = f"subtitles='{_filter_path(subtitle_file)}':force_style='{style}'"
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(input_video),
           "-vf", vf, "-an"]
    cmd += encoder_args or ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    cmd += ["-movflags", "+faststart", str(output_video)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not output_video.is_file() or output_video.stat().st_size < 5000:
        raise RuntimeError("Subtitle burn-in failed: " + (result.stderr or "")[-3000:])
    return output_video


def load_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
