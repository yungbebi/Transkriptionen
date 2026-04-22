# Transkriptionen

Minimal local macOS-first transcription tool that turns `audio/*.mp4` into MAXQDA-style Markdown transcripts with speaker-separated, timestamped chunks.

## Setup

```bash
mise use -g python@3.11
poetry init -n
poetry add whisperx torch torchaudio
brew install ffmpeg
```

Then install project dependencies:

```bash
poetry install
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
