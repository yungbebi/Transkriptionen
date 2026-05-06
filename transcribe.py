from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

# Suppress all the pyannote/torch noise before any imports
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import mlx_whisper
import numpy as np
import torch


# ---------------------------------------------------------------------------
# Logging (can be overridden by passing a log callback)
# ---------------------------------------------------------------------------

_log_callback = None


def set_log_callback(fn):
    global _log_callback
    _log_callback = fn


def _log(msg: str):
    if _log_callback:
        _log_callback(msg)
    else:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Model cache (avoid reloading on every transcription)
# ---------------------------------------------------------------------------

_WHISPER_MODEL_NAME = "mlx-community/whisper-large-v3-mlx"
_DIARIZATION_PIPELINE = None


def get_diarization_pipeline():
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            raise RuntimeError("HF_TOKEN is required for diarization. Set it with: export HF_TOKEN=your_token")
        from pyannote.audio import Pipeline as PyannotePipeline
        device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
        _log(f"Loading diarization pipeline on {device}...")
        _DIARIZATION_PIPELINE = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        _DIARIZATION_PIPELINE.to(device)
    return _DIARIZATION_PIPELINE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_ts(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_audio(path: Path) -> np.ndarray:
    """Load audio as 16kHz mono float32 numpy array via ffmpeg."""
    import subprocess
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", str(path),
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le",
        "-ar", "16000", "-",
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # silence ffmpeg output
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to load: {path}")
    audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def assign_speakers(whisper_segments: list[dict], diarization) -> list[dict]:
    """
    Map pyannote speaker labels onto whisper segments by maximum temporal overlap.
    Returns segments with a 'speaker' key added.
    """
    # Build flat list of (start, end, speaker) from pyannote annotation
    diar_turns = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]

    result = []
    for seg in whisper_segments:
        s_start = float(seg.get("start", 0))
        s_end = float(seg.get("end", s_start))
        text = (seg.get("text") or "").strip()
        if not text:
            continue

        best_speaker = "Unknown"
        best_overlap = 0.0
        for d_start, d_end, speaker in diar_turns:
            overlap = min(s_end, d_end) - max(s_start, d_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker

        result.append({
            "speaker": best_speaker,
            "start": s_start,
            "end": s_end,
            "text": text,
        })
    return result


def normalize_and_merge(segments: list[dict]) -> list[dict]:
    """Normalize speaker labels (SPEAKER_00 → Speaker 1) and merge consecutive same-speaker chunks."""
    speaker_map: dict[str, str] = {}
    merged: list[dict] = []

    for seg in segments:
        raw = seg["speaker"]
        if raw not in speaker_map:
            speaker_map[raw] = f"Speaker {len(speaker_map) + 1}"
        speaker = speaker_map[raw]

        if merged and merged[-1]["speaker"] == speaker:
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = f"{merged[-1]['text']} {seg['text']}".strip()
        else:
            merged.append({"speaker": speaker, "start": seg["start"], "end": seg["end"], "text": seg["text"]})

    return merged


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

MODEL = "mlx-community/whisper-large-v3-mlx"


def transcribe_file(input_path: Path, min_speakers: int = 1, max_speakers: int = 3, diarize: bool = True) -> list[dict]:
    # 1. Transcribe with mlx-whisper (uses Apple Silicon GPU natively)
    _log("Loading audio...")
    audio = load_audio(input_path)

    _log(f"Transcribing with mlx-whisper ({_WHISPER_MODEL_NAME})...")
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=_WHISPER_MODEL_NAME,
        word_timestamps=True,
        verbose=False,
    )
    segments = result.get("segments", [])
    language = result.get("language", "unknown")
    _log(f"Language detected: {language} | Segments: {len(segments)}")

    if not diarize:
        _log("Skipping diarization — using single speaker...")
        merged: list[dict] = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            if merged and merged[-1]["speaker"] == "Speaker 1":
                merged[-1]["end"] = float(seg.get("end", merged[-1]["end"]))
                merged[-1]["text"] = f"{merged[-1]['text']} {text}".strip()
            else:
                merged.append({
                    "speaker": "Speaker 1",
                    "start": float(seg.get("start", 0)),
                    "end": float(seg.get("end", 0)),
                    "text": text,
                })
        return merged

    # 2. Diarize with pyannote (cached pipeline)
    _log("Running speaker diarization...")
    pipeline = get_diarization_pipeline()
    waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, samples)
    diarization_kwargs = {"waveform": waveform, "sample_rate": 16000}
    if min_speakers is not None:
        diarization_kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        diarization_kwargs["max_speakers"] = max_speakers
    diarization = pipeline(diarization_kwargs)

    # 3. Assign speakers + merge
    _log("Aligning transcript with speakers...")
    segments_with_speakers = assign_speakers(segments, diarization)
    return normalize_and_merge(segments_with_speakers)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_markdown(segments: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for seg in segments:
        lines.extend([
            f"## {seg['speaker']}",
            f"[{format_ts(seg['start'])}–{format_ts(seg['end'])}]",
            seg["text"],
            "",
        ])
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio with mlx-whisper + pyannote diarization")
    parser.add_argument("input_file", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--diarize", action="store_true", help="Enable speaker diarization (slower)")
    parser.add_argument("--min-speakers", type=int, default=1, help="Expected minimum number of speakers")
    parser.add_argument("--max-speakers", type=int, default=3, help="Expected maximum number of speakers")
    args = parser.parse_args()

    output_path = args.output or Path("transcripts") / f"{args.input_file.stem}.md"

    if output_path.exists() and not args.force:
        _log(f"Skipping: {output_path} exists (use --force to overwrite)")
        return

    if not args.input_file.exists():
        _log(f"Error: file not found: {args.input_file}")
        sys.exit(1)

    segments = transcribe_file(
        args.input_file,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        diarize=args.diarize,
    )
    write_markdown(segments, output_path)
    _log(f"Done: {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
