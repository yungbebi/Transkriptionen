from __future__ import annotations

import subprocess
import sys
import threading
import json
import time
from pathlib import Path
from flask import Flask, render_template_string, request, redirect, url_for, send_file, jsonify, Response
from collections import deque

AUDIO_DIR = Path("audio")
TRANSCRIPTS_DIR = Path("transcripts")

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Log stream
log_queue = deque(maxlen=100)
# Track active transcription processes
active_processes: dict[str, subprocess.Popen] = {}


def add_log(message: str):
    """Add message to log queue"""
    log_queue.append({
        "timestamp": time.time() * 1000,
        "message": message
    })
    print(f"[LOG] {message}", file=sys.stderr)


def audio_files() -> list[Path]:
    AUDIO_DIR.mkdir(exist_ok=True)
    return sorted(AUDIO_DIR.glob("*.mp4")) + sorted(AUDIO_DIR.glob("*.m4a")) + sorted(AUDIO_DIR.glob("*.mp3")) + sorted(AUDIO_DIR.glob("*.wav"))


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
    files = []
    
    # Get all audio files
    audio_set = {af.stem: af for af in audio_files()}
    
    # Get all transcripts
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    for transcript_file in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        stem = transcript_file.stem
        audio_file = audio_set.get(stem)
        if audio_file:
            files.append({
                "name": audio_file.name,
                "has_transcript": True,
                "size": transcript_file.stat().st_size
            })
            del audio_set[stem]
    
    # Add remaining audio files without transcripts
    for stem, audio_file in sorted(audio_set.items()):
        files.append({
            "name": audio_file.name,
            "has_transcript": False,
            "size": audio_file.stat().st_size
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
    """Run transcription in background thread with real-time log streaming"""
    cmd = [sys.executable, "transcribe.py", str(audio_path), "-o", str(output_path), "--force"]
    try:
        add_log(f"▶️  Starting: {filename}")
        
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        active_processes[filename] = process
        
        # Read and log each line as it comes
        for line in iter(process.stdout.readline, ''):
            if line:
                line = line.strip()
                if line and not line.startswith('2026-'):  # Skip timestamp logs
                    add_log(line)
        
        process.wait()
        
        if filename in active_processes:
            del active_processes[filename]
        
        if process.returncode == 0 and output_path.exists():
            size = output_path.stat().st_size
            add_log(f"✅ Success: {filename} ({size} bytes)")
        else:
            add_log(f"❌ Failed with exit code {process.returncode}")
    except Exception as e:
        if filename in active_processes:
            del active_processes[filename]
        add_log(f"⚠️  Exception: {str(e)[:150]}")


@app.route("/stop/<filename>", methods=["POST"])
def stop_transcription(filename):
    """Stop an active transcription"""
    if filename in active_processes:
        try:
            process = active_processes[filename]
            process.terminate()
            process.wait(timeout=5)
            del active_processes[filename]
            add_log(f"⏹️  Stopped: {filename}")
            return jsonify({"success": True, "message": "Transcription stopped"})
        except Exception as e:
            add_log(f"❌ Failed to stop: {str(e)}")
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": False, "error": "Not transcribing"})


@app.route("/logs")
def logs():
    def event_stream():
        # Send existing logs
        for log in log_queue:
            yield f"data: {json.dumps(log)}\n\n"
        
        # Stream new logs
        last_seen = len(log_queue)
        while True:
            if len(log_queue) > last_seen:
                for log in list(log_queue)[last_seen:]:
                    yield f"data: {json.dumps(log)}\n\n"
                last_seen = len(log_queue)
            time.sleep(0.1)
    
    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_json()
    filename = data.get("filename")
    
    audio_path = AUDIO_DIR / filename
    if not audio_path.exists():
        return jsonify({"success": False, "error": "File not found"})
    
    output_path = TRANSCRIPTS_DIR / f"{audio_path.stem}.md"
    
    # Check if already transcribed
    if output_path.exists():
        return jsonify({"success": True, "message": "Already transcribed"})
    
    # Check if already transcribing
    if filename in active_processes:
        return jsonify({"success": False, "error": "Already transcribing"})
    
    # Start transcription in background thread (non-blocking)
    thread = threading.Thread(target=run_transcription, args=(filename, audio_path, output_path), daemon=True)
    thread.start()
    
    # Poll for file completion (with timeout)
    import time
    for i in range(240):  # Wait up to 4 minutes for the file to appear
        if output_path.exists():
            time.sleep(0.5)  # Small delay to ensure file is fully written
            return jsonify({"success": True, "message": "Transcription complete"})
        time.sleep(1)
    
    return jsonify({"success": True, "message": "Transcription started in background"})


@app.route("/view/<filename>", methods=["GET"])
def view_transcript(filename):
    audio_path = AUDIO_DIR / filename
    transcript_path = TRANSCRIPTS_DIR / f"{audio_path.stem}.md"
    
    if transcript_path.exists():
        return send_file(transcript_path, mimetype="text/markdown")
    return "Not found", 404


@app.route("/delete", methods=["POST"])
def delete_file():
    """Only delete transcript (MD) files, never audio files"""
    data = request.get_json()
    filename = data.get("filename")
    
    audio_path = AUDIO_DIR / filename
    transcript_path = TRANSCRIPTS_DIR / f"{audio_path.stem}.md"
    
    # Only delete the transcript, never the audio file
    if transcript_path.exists():
        transcript_path.unlink()
        add_log(f"🗑️  Deleted transcript: {transcript_path.name}")
    
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False, use_reloader=False)
