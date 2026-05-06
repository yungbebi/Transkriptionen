from __future__ import annotations

import sys
import json
import time
import subprocess
from pathlib import Path
from flask import Flask, render_template_string, request, send_file, jsonify, Response
from collections import deque

AUDIO_DIR = Path("audio")
TRANSCRIPTS_DIR = Path("transcripts")

app = Flask(__name__)

log_queue: deque = deque(maxlen=500)
active_processes: dict[str, subprocess.Popen] = {}

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def add_log(msg: str):
    entry = {"timestamp": time.time() * 1000, "message": msg}
    log_queue.append(entry)
    print("[LOG]", msg, flush=True)


# ---------------------------------------------------------------------------
# FILES
# ---------------------------------------------------------------------------

def audio_files():
    AUDIO_DIR.mkdir(exist_ok=True)
    return sorted(AUDIO_DIR.glob("*.*"))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Transcribe</title></head>
<body>
<h1>Transcription</h1>
<input type="file" id="file" />
<button onclick="upload()">Upload</button>
<div id="files"></div>
<pre id="logs"></pre>

<script>
async function refresh() {
    let r = await fetch('/files');
    let data = await r.json();
    let html = '';
    data.files.forEach(f => {
        html += f.name + ' ';
        html += f.transcribed ? '[done]' :
            `<button onclick="run('${f.name}')">run</button>
             <button onclick="stop('${f.name}')">stop</button>`;
        html += '<br>';
    });
    document.getElementById('files').innerHTML = html;
}
async function run(name){
    await fetch('/transcribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:name})});
}
async function stop(name){
    await fetch('/stop/'+name,{method:'POST'});
}
async function upload(){
    let f=document.getElementById('file').files[0];
    let fd=new FormData(); fd.append('file',f);
    await fetch('/upload',{method:'POST',body:fd});
    refresh();
}
refresh();

let es=new EventSource('/logs');
es.onmessage=e=>{
    let d=JSON.parse(e.data);
    document.getElementById('logs').textContent += d.message + "\\n";
};
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return HTML


@app.route("/files")
def files():
    AUDIO_DIR.mkdir(exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)

    files = []
    for f in audio_files():
        out = TRANSCRIPTS_DIR / (f.stem + ".md")
        files.append({
            "name": f.name,
            "transcribed": out.exists()
        })
    return jsonify({"files": files})


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files["file"]
    AUDIO_DIR.mkdir(exist_ok=True)
    path = AUDIO_DIR / f.filename
    f.save(path)
    add_log(f"uploaded: {f.filename}")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# CORE: PROCESS-BASED EXECUTION
# ---------------------------------------------------------------------------

def build_command(audio_path: Path, output_path: Path):
    return [
        sys.executable,
        "transcribe.py",
        str(audio_path),
        "--diarize",
        "--output", str(output_path),
        "--force"
    ]


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.json
    filename = data["filename"]

    if filename in active_processes:
        return jsonify({"error": "already running"}), 400

    audio_path = AUDIO_DIR / filename
    output_path = TRANSCRIPTS_DIR / (audio_path.stem + ".md")

    cmd = build_command(audio_path, output_path)

    proc = subprocess.Popen(
        cmd,
        env={**os.environ, "HF_TOKEN": os.environ.get("HF_TOKEN", "")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    active_processes[filename] = proc
    add_log(f"▶ started: {filename}")

    # stream logs in background
    def stream():
        for line in proc.stdout:
            if line.strip():
                add_log(line.strip())

        proc.wait()
        active_processes.pop(filename, None)

        if proc.returncode == 0:
            add_log(f"✅ done: {filename}")
        else:
            add_log(f"❌ failed: {filename}")

    import threading
    threading.Thread(target=stream, daemon=True).start()

    return jsonify({"ok": True})


@app.route("/stop/<filename>", methods=["POST"])
def stop(filename):
    proc = active_processes.get(filename)
    if not proc:
        return jsonify({"error": "not running"}), 400

    proc.terminate()
    active_processes.pop(filename, None)
    add_log(f"⏹ stopped: {filename}")

    return jsonify({"ok": True})


@app.route("/logs")
def logs():
    def gen():
        last = 0
        while True:
            if len(log_queue) > last:
                for e in list(log_queue)[last:]:
                    yield f"data: {json.dumps(e)}\n\n"
                last = len(log_queue)
            time.sleep(0.2)

    return Response(gen(), mimetype="text/event-stream")


@app.route("/view/<filename>")
def view(filename):
    path = TRANSCRIPTS_DIR / (Path(filename).stem + ".md")
    return send_file(path) if path.exists() else ("not found", 404)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(port=8000, debug=False)