from __future__ import annotations

import argparse
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import mlx_whisper
import numpy as np
import torch
from functools import lru_cache

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

WHISPER_MODEL = "mlx-community/whisper-small-mlx"  # faster
CHUNK_SECONDS = 300  # 5 min chunks (huge speed improvement)
FAST_MODE = True  # toggle speed vs accuracy

# ---------------------------------------------------------------------------
# CACHE
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_model():
    return mlx_whisper.load_models.load_model(WHISPER_MODEL)


_DIARIZATION_PIPELINE = None


def get_diarization_pipeline():
    global _DIARIZATION_PIPELINE
    if _DIARIZATION_PIPELINE is None:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            raise RuntimeError("HF_TOKEN required")

        from pyannote.audio import Pipeline

        # CPU is often more stable on mac than MPS for pyannote
        device = torch.device("cpu")

        _DIARIZATION_PIPELINE = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        _DIARIZATION_PIPELINE.to(device)

    return _DIARIZATION_PIPELINE


# ---------------------------------------------------------------------------
# AUDIO
# ---------------------------------------------------------------------------

def load_audio(path: Path) -> np.ndarray:
    import subprocess

    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", str(path),
        "-f", "s16le", "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", "16000", "-",
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed")

    return np.frombuffer(result.stdout, np.int16).astype(np.float32) / 32768.0


def chunk_audio(audio: np.ndarray, sr: int = 16000):
    chunk_size = sr * CHUNK_SECONDS
    for i in range(0, len(audio), chunk_size):
        yield i / sr, audio[i:i + chunk_size]


# ---------------------------------------------------------------------------
# TRANSCRIPTION
# ---------------------------------------------------------------------------

def transcribe_chunks(audio: np.ndarray):
    model = load_model()

    all_segments = []

    for offset, chunk in chunk_audio(audio):
        result = mlx_whisper.transcribe(
            chunk,
            path_or_hf_repo=WHISPER_MODEL,
            word_timestamps=False if FAST_MODE else True,
            verbose=False,
        )

        for seg in result.get("segments", []):
            seg["start"] += offset
            seg["end"] += offset
            all_segments.append(seg)

    return all_segments


# ---------------------------------------------------------------------------
# DIARIZATION
# ---------------------------------------------------------------------------

def diarize(audio: np.ndarray, min_speakers, max_speakers):
    pipeline = get_diarization_pipeline()

    waveform = torch.from_numpy(audio).unsqueeze(0)

    return pipeline({
        "waveform": waveform,
        "sample_rate": 16000,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
    })


# ---------------------------------------------------------------------------
# ALIGN
# ---------------------------------------------------------------------------

def assign_speakers(segments, diarization):
    diar_turns = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]

    out = []
    for seg in segments:
        s, e = seg["start"], seg["end"]
        best = "Speaker 1"
        best_overlap = 0

        for ds, de, spk in diar_turns:
            overlap = min(e, de) - max(s, ds)
            if overlap > best_overlap:
                best_overlap = overlap
                best = spk

        out.append({
            "speaker": best,
            "start": s,
            "end": e,
            "text": seg["text"].strip(),
        })

    return out


def merge_segments(segments, max_gap=2.0):
    merged = []
    mapping = {}

    for seg in segments:
        spk = seg["speaker"]

        if spk not in mapping:
            mapping[spk] = f"Speaker {len(mapping)+1}"

        spk = mapping[spk]

        if merged:
            prev = merged[-1]

            same_speaker = prev["speaker"] == spk
            close_in_time = seg["start"] - prev["end"] <= max_gap

            if same_speaker and close_in_time:
                prev["end"] = seg["end"]
                prev["text"] += " " + seg["text"]
                continue

        merged.append({
            "speaker": spk,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })

    return merged

# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------

def format_ts(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def write_md(segments, path):
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for s in segments:
        lines += [
            f"## {s['speaker']}",
            f"[{format_ts(s['start'])}–{format_ts(s['end'])}]",
            s["text"],
            "",
        ]

    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_file", type=Path)
    p.add_argument("--diarize", action="store_true")
    p.add_argument("--min-speakers", type=int, default=1)
    p.add_argument("--max-speakers", type=int, default=3)
    args = p.parse_args()

    audio = load_audio(args.input_file)

    print("Transcribing...")
    segments = transcribe_chunks(audio)

    if not args.diarize:
        for s in segments:
            s["speaker"] = "Speaker 1"
        final = merge_segments(segments)
    else:
        print("Diarizing...")
        diar = diarize(audio, args.min_speakers, args.max_speakers)
        aligned = assign_speakers(segments, diar)
        final = merge_segments(aligned)

    out = Path("transcripts") / (args.input_file.stem + ".md")
    write_md(final, out)

    print("Done:", out)


if __name__ == "__main__":
    main()