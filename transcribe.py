from __future__ import annotations

import argparse
import os
from pathlib import Path

import torch
import whisperx


def format_ts(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def normalize_and_merge(segments: list[dict]) -> list[dict]:
    speaker_map: dict[str, str] = {}
    normalized: list[dict] = []

    for seg in segments:
        raw_speaker = seg.get("speaker") or "Unknown"
        speaker = speaker_map.setdefault(raw_speaker, f"Speaker {len(speaker_map) + 1}")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if normalized and normalized[-1]["speaker"] == speaker:
            normalized[-1]["end"] = max(normalized[-1]["end"], end)
            normalized[-1]["text"] = f"{normalized[-1]['text']} {text}".strip()
            continue
        normalized.append({"speaker": speaker, "start": start, "end": end, "text": text})
    return normalized


def transcribe_file(input_path: Path) -> list[dict]:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    audio = whisperx.load_audio(str(input_path))

    model = whisperx.load_model("large-v2", device, compute_type=compute_type)
    result = model.transcribe(audio, batch_size=16)

    model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)

    diarize_model = whisperx.DiarizationPipeline(use_auth_token=os.getenv("HF_TOKEN"), device=device)
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    return normalize_and_merge(result["segments"])


def write_markdown(segments: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for seg in segments:
        lines.extend(
            [
                f"## {seg['speaker']}",
                f"[{format_ts(seg['start'])}–{format_ts(seg['end'])}]",
                seg["text"],
                "",
            ]
        )
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output_path = args.output or Path("transcripts") / f"{args.input_file.stem}.md"
    if output_path.exists() and not args.force:
        print(f"Skipping: {output_path} exists (use --force to overwrite)")
        return

    segments = transcribe_file(args.input_file)
    write_markdown(segments, output_path)
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
