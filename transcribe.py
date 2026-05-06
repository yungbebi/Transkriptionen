from __future__ import annotations

import os
import numpy as np
import torch
import mlx_whisper
from pathlib import Path
from functools import lru_cache
from huggingface_hub import login
from pyannote.audio import Pipeline
from pyannote.audio.pipelines.speaker_diarization import DiarizeOutput

# -----------------------------
# HF AUTH
# -----------------------------

HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN missing")

login(token=HF_TOKEN)

# -----------------------------
# MODEL
# -----------------------------

MODEL = "mlx-community/whisper-large-v3-mlx"

# -----------------------------
# LOAD DIARIZATION PIPELINE
# -----------------------------

@lru_cache(maxsize=1)
def load_diarization():
    pipe = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=HF_TOKEN
    )
    return pipe

# -----------------------------
# AUDIO LOADING
# -----------------------------

def load_audio(path: Path):
    import subprocess

    cmd = [
        "ffmpeg", "-i", str(path),
        "-ac", "1",
        "-ar", "16000",
        "-f", "s16le",
        "-"
    ]

    audio = subprocess.check_output(cmd)
    return np.frombuffer(audio, np.int16).astype(np.float32) / 32768.0

# -----------------------------
# TRANSCRIPTION
# -----------------------------

def transcribe(audio):
    return mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL,
        word_timestamps=False
    )

# -----------------------------
# DIARIZATION (FIXED)
# -----------------------------

def diarize(audio_path: Path, min_speakers=None, max_speakers=None):
    """
    IMPORTANT FIX:
    pyannote 3.x expects FILE PATH, not waveform dict
    """

    pipe = load_diarization()
    kwargs = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    return pipe(str(audio_path), **kwargs)

# -----------------------------
# TURN EXTRACTION (ROBUST)
# -----------------------------

def extract_turns(diar):
    """
    Converts pyannote output to (start, end, speaker)
    """

    turns = []

    # Handle pyannote 3.x DiarizeOutput
    if isinstance(diar, DiarizeOutput):
        diar = diar.exclusive_speaker_diarization

    # Standard pyannote Annotation
    if hasattr(diar, "itertracks"):
        for segment, _, speaker in diar.itertracks(yield_label=True):
            turns.append((segment.start, segment.end, speaker))
        return turns

    raise TypeError(f"Unsupported diarization format: {type(diar)}")

# -----------------------------
# ALIGNMENT
# -----------------------------

def align(segments, diar):
    turns = extract_turns(diar)

    out = []

    for seg in segments:
        best = "Unknown"
        best_score = 0

        for s, e, spk in turns:
            overlap = max(
                0,
                min(e, seg["end"]) - max(s, seg["start"])
            )
            if overlap > best_score:
                best_score = overlap
                best = spk

        out.append({
            "speaker": best,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"]
        })

    return out

# -----------------------------
# MAIN
# -----------------------------

def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--diarize", action="store_true")
    ap.add_argument("--min-speakers", type=int, default=None)
    ap.add_argument("--max-speakers", type=int, default=None)
    args = ap.parse_args()

    path = Path(args.file)

    # Create transcripts directory
    transcripts_dir = Path("transcripts")
    transcripts_dir.mkdir(exist_ok=True)

    # Output file path
    stem = path.stem
    out_path = transcripts_dir / f"{stem}.txt"

    print("Loading audio...")
    audio = load_audio(path)

    print("Transcribing...")
    result = transcribe(audio)
    segments = result["segments"]

    if not args.diarize:
        lines = [f"[{s['start']:.2f} - {s['end']:.2f}] {s['text']}" for s in segments]
        text = "\n".join(lines)
        out_path.write_text(text)
        print(text)
        print(f"\nSaved to: {out_path}")
        return

    print("Diarizing...")
    diar = diarize(path, args.min_speakers, args.max_speakers)

    print("Aligning...\n")

    final = align(segments, diar)

    lines = [f"[{s['start']:.2f} - {s['end']:.2f}] {s['speaker']}: {s['text']}" for s in final]
    text = "\n".join(lines)
    out_path.write_text(text)

    for line in lines:
        print(line)

    print(f"\nSaved to: {out_path}")

if __name__ == "__main__":
    main()