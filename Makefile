.PHONY: help setup install run clean kill transcribe

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
PORT   := 8000

help:
	@echo "📝 Transkriptionen"
	@echo "  make setup        - Create Python 3.12 venv"
	@echo "  make install      - Install dependencies"
	@echo "  make run          - Start the web UI"
	@echo "  make transcribe FILE=audio/file.m4a - Transcribe with defaults (--diarize --max-speakers 2)"
	@echo "  make clean        - Remove venv and transcripts"
	@echo "  make kill         - Kill process on port $(PORT)"

setup:
	@echo "🔧 Creating venv..."
	python3.12 -m venv .venv
	@echo "✅ Done"

install:
	@echo "📦 Installing dependencies..."
	$(PIP) install --upgrade pip --quiet
	# Flask
	$(PIP) install flask python-dotenv --quiet
	# torch (default PyPI build includes MPS for Apple Silicon — no --index-url needed)
	$(PIP) install torch torchaudio --quiet
	# mlx-whisper: native Apple Silicon transcription, no CTranslate2
	$(PIP) install mlx-whisper --quiet
	# pyannote for speaker diarization (runs on CPU, fast enough)
	$(PIP) install pyannote.audio --quiet
	# ffmpeg-python for audio loading
	$(PIP) install ffmpeg-python --quiet
	@echo ""
	@echo "✅ Done. Make sure you also have:"
	@echo "   brew install ffmpeg"
	@echo "   export HF_TOKEN=your_huggingface_token"

run: kill
	@echo "🚀 Starting..."
	@(sleep 2 && open "http://127.0.0.1:$(PORT)") &
	@$(PYTHON) -W ignore app.py --no-diarize 2>&1 | cat

kill:
	@lsof -ti:$(PORT) | xargs kill -9 2>/dev/null || true
	@sleep 0.5

clean:
	@echo "🧹 Cleaning..."
	@rm -rf .venv transcripts __pycache__ *.pyc
	@echo "✅ Done"

.venv:
	python3.12 -m venv .venv

transcribe:
	@test -n "$(FILE)" || (echo "❌ Usage: make transcribe FILE=audio/your_file.m4a"; exit 1)
	@echo "🎙️  Transcribing $(FILE)..."
	@source .env && $(PYTHON) transcribe.py --diarize --max-speakers 2 "$(FILE)"
