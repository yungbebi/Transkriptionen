.PHONY: help setup install run clean kill

PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PORT := 8000

help:
	@echo "📝 Transkriptionen - Available commands:"
	@echo "  make setup    - Create Python virtual environment"
	@echo "  make install  - Install dependencies"
	@echo "  make run      - Start the web UI"
	@echo "  make clean    - Remove venv and transcripts"
	@echo "  make kill     - Kill process on port 8000"

setup:
	@echo "🔧 Creating virtual environment with Python 3.12..."
	python3.12 -m venv .venv
	@echo "✅ Virtual environment created"

install:
	@echo "📦 Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install flask python-dotenv
	$(PIP) install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
	$(PIP) install git+https://github.com/m-bain/whisperx.git
	@echo "✅ Dependencies installed"

run: kill
	@echo "🚀 Starting Transkriptionen web UI..."
	@echo "📂 Opening http://127.0.0.1:$(PORT)..."
	@(sleep 2 && open "http://127.0.0.1:$(PORT)") &
	@$(PYTHON) app.py 2>&1 | grep -v "WARNING\|GET\|POST"

kill:
	@lsof -ti:$(PORT) | xargs kill -9 2>/dev/null || true
	@sleep 0.5

clean:
	@echo "🧹 Cleaning up..."
	@rm -rf .venv transcripts __pycache__ *.pyc
	@echo "✅ Clean complete"

.venv:
	python3.12 -m venv .venv
