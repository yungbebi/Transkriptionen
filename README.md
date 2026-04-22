# Transkriptionen

Minimal local macOS-first transcription tool that turns `audio/*.mp4` into MAXQDA-style Markdown transcripts with speaker-separated, timestamped chunks.

## Setup

If you are creating this setup from scratch, these are the exact commands:

```bash
mise use -g python@3.11
poetry init -n
poetry add whisperx torch torchaudio
brew install ffmpeg
```

`mise` is a lightweight runtime/version manager used here to pin Python 3.11.

For this repository, install dependencies with:

```bash
poetry install
```

Set a Hugging Face token for diarization:

```bash
export HF_TOKEN=your_hf_token
```

## Run the local UI

```bash
poetry run python app.py
```

Open: http://localhost:8000

## CLI usage

```bash
poetry run python transcribe.py audio/file.mp4
poetry run python transcribe.py audio/file.mp4 -o transcripts/file.md
poetry run python transcribe.py audio/file.mp4 --force
```

Behavior:

- Input: `audio/*.mp4`
- Output: `transcripts/*.md`
- Idempotent unless `--force`
