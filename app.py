from __future__ import annotations

import sys
import threading
import json
import time
from pathlib import Path
from flask import Flask, render_template_string, request, send_file, jsonify, Response
from collections import deque

# Import transcription pipeline directly so models stay loaded in the Flask process
from transcribe import transcribe_file, write_markdown, set_log_callback

# Wire transcribe.py _log() into our log queue
set_log_callback(lambda msg: add_log(msg) if not _is_noise(msg) else None)

AUDIO_DIR = Path("audio")
TRANSCRIPTS_DIR = Path("transcripts")

app = Flask(__name__, static_folder="static", static_url_path="/static")

log_queue: deque = deque(maxlen=200)
active_processes: dict[str, subprocess.Popen] = {}

# Lines containing any of these strings are dropped from the log display
LOG_NOISE = (
    "UserWarning", "FutureWarning", "DeprecationWarning",
    "torchcodec", "libtorchcodec", "libavutil", "dlopen", "OSError:",
    "site-packages", "torch.ops", "load_library", "ctypes",
    "Traceback (most recent", "  File \"/", "    ", "^^^^^",
    "Lightning automatically", "warnings.warn", "filterwarnings",
    "TOKENIZERS_PARALLELISM", "ffmpeg version", "ffmpeg",
    "built with", "configuration:", "libavcodec", "libavformat",
    "libswresample", "encoder", "Input #", "Output #",
    "Stream #", "size=", "time=", "bitrate=", "speed=",
    "PyTorch version", "No CUDA", "MPS", "Using device",
)


def _is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return any(s in stripped for s in LOG_NOISE)


def add_log(message: str):
    entry = {"timestamp": time.time() * 1000, "message": message}
    log_queue.append(entry)
    print(f"[LOG] {message}", file=sys.stderr, flush=True)


def audio_files() -> list[Path]:
    AUDIO_DIR.mkdir(exist_ok=True)
    exts = ("*.mp4", "*.m4a", "*.mp3", "*.wav")
    files = []
    for ext in exts:
        files.extend(AUDIO_DIR.glob(ext))
    return sorted(files)


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Transkriptionen</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="container">
        <h1>🎙️ Transkriptionen</h1>

        <div class="dropzone" id="dropzone">
            <p>Drag & drop audio files here</p>
            <small>or click to browse (MP4, M4A, MP3, WAV)</small>
            <input type="file" id="file-input" class="file-input" multiple accept=".mp4,.m4a,.mp3,.wav" />
        </div>

        <div id="files-list" class="files-section"></div>

        <h3>Live Logs</h3>
        <div id="logs" class="logs-container"></div>
    </div>

    <script src="/static/app.js"></script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    AUDIO_DIR.mkdir(exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    return render_template_string(HTML_TEMPLATE)


@app.route("/files", methods=["GET"])
def get_files():
    AUDIO_DIR.mkdir(exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)

    audio_set = {af.stem: af for af in audio_files()}
    files = []

    for transcript_file in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        stem = transcript_file.stem
        audio_file = audio_set.pop(stem, None)
        if audio_file:
            files.append({
                "name": audio_file.name,
                "transcribed": True,
                "size": audio_file.stat().st_size,
                "transcript_size": transcript_file.stat().st_size,
            })

    for stem, audio_file in sorted(audio_set.items()):
        files.append({
            "name": audio_file.name,
            "transcribed": False,
            "size": audio_file.stat().st_size,
        })

    return jsonify({"files": files})


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file"})
    file = request.files["file"]
    AUDIO_DIR.mkdir(exist_ok=True)
    filepath = AUDIO_DIR / file.filename
    file.save(str(filepath))
    return jsonify({"success": True, "path": str(filepath)})


def run_transcription(filename: str, audio_path: Path, output_path: Path):
    try:
        add_log(f"▶️  Starting: {filename}")
        active_processes[filename] = True  # mark as running

        segments = transcribe_file(audio_path, min_speakers=1, max_speakers=3, diarize=False)
        write_markdown(segments, output_path)

        active_processes.pop(filename, None)
        add_log(f"✅ Done: {filename} ({output_path.stat().st_size:,} bytes)")
    except Exception as e:
        active_processes.pop(filename, None)
        add_log(f"⚠️  Error: {str(e)[:200]}")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json()
    filename = data.get("filename")
    audio_path = AUDIO_DIR / filename

    if not audio_path.exists():
        return jsonify({"success": False, "error": "File not found"})

    output_path = TRANSCRIPTS_DIR / f"{audio_path.stem}.md"

    if output_path.exists():
        return jsonify({"success": True, "message": "Already transcribed"})

    if filename in active_processes:
        return jsonify({"success": False, "error": "Already in progress"})

    thread = threading.Thread(
        target=run_transcription,
        args=(filename, audio_path, output_path),
        daemon=True,
    )
    thread.start()

    # Poll up to 10 minutes; long audio files take time
    for _ in range(600):
        if output_path.exists():
            time.sleep(0.5)
            return jsonify({"success": True, "message": "Transcription complete"})
        time.sleep(1)

    return jsonify({"success": True, "message": "Running in background — check logs"})


@app.route("/stop/<filename>", methods=["POST"])
def stop_transcription(filename):
    proc = active_processes.get(filename)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
            active_processes.pop(filename, None)
            add_log(f"⏹️  Stopped: {filename}")
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": False, "error": "Not running"})


@app.route("/logs")
def logs():
    def event_stream():
        for entry in list(log_queue):
            yield f"data: {json.dumps(entry)}\n\n"
        last_seen = len(log_queue)
        while True:
            current = len(log_queue)
            if current > last_seen:
                for entry in list(log_queue)[last_seen:]:
                    yield f"data: {json.dumps(entry)}\n\n"
                last_seen = current
            time.sleep(0.1)

    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/view/<filename>", methods=["GET"])
def view_transcript(filename):
    transcript_path = TRANSCRIPTS_DIR / f"{Path(filename).stem}.md"
    if transcript_path.exists():
        return send_file(transcript_path, mimetype="text/markdown")
    return "Not found", 404


@app.route("/delete", methods=["POST"])
def delete_file():
    data = request.get_json()
    filename = data.get("filename")
    transcript_path = TRANSCRIPTS_DIR / f"{Path(filename).stem}.md"
    if transcript_path.exists():
        transcript_path.unlink()
        add_log(f"🗑️  Deleted: {transcript_path.name}")
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False, use_reloader=False)
