# Transkriptionen

Minimal local macOS-first transcription tool that turns `audio/*.mp4` into MAXQDA-style Markdown transcripts with speaker-separated, timestamped chunks.

## Setup

If you are creating this setup from scratch:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install git+https://github.com/m-bain/whisperx.git
pip install gradio ffmpeg-python torch torchvision torchaudio flask
brew install ffmpeg
```

For this repository, install dependencies with:

```bash
pip install -r requirements.txt
```

or with Poetry:

```bash
poetry install
```

Set a Hugging Face token for diarization:

```bash
export HF_TOKEN=your_hf_token
```

## Run the local Web UI

```bash
python app.py
```

Open: http://localhost:8000

## CLI usage

```bash
python transcribe.py audio/file.mp4
python transcribe.py audio/file.mp4 -o transcripts/file.md
python transcribe.py audio/file.mp4 --force
```

Behavior:

- Input: `audio/*.mp4`
- Output: `transcripts/*.md`
- Idempotent unless `--force`
