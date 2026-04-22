from __future__ import annotations

import html
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


AUDIO_DIR = Path("audio")
TRANSCRIPTS_DIR = Path("transcripts")


def audio_files() -> list[Path]:
    AUDIO_DIR.mkdir(exist_ok=True)
    return sorted(AUDIO_DIR.glob("*.mp4"))


def page() -> str:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    rows: list[str] = []
    for idx, mp4 in enumerate(audio_files()):
        transcript = TRANSCRIPTS_DIR / f"{mp4.stem}.md"
        link = f'<a href="/transcript?id={idx}">transcript</a>' if transcript.exists() else "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(mp4.name)}</td>"
            "<td>"
            '<form method="post" action="/run">'
            f'<input type="hidden" name="id" value="{idx}">'
            '<label><input type="checkbox" name="force" value="1"> force</label> '
            '<button type="submit">transcribe</button>'
            "</form>"
            "</td>"
            f"<td>{link}</td>"
            "</tr>"
        )
    rows_html = "".join(rows) or '<tr><td colspan="3">No .mp4 files in audio/</td></tr>'
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Transkriptionen</title></head><body>"
        "<h1>Transkriptionen</h1>"
        "<table border='1' cellpadding='6'><tr><th>file</th><th>action</th><th>output</th></tr>"
        f"{rows_html}</table>"
        "</body></html>"
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/transcript":
            query = parse_qs(parsed.query)
            try:
                idx = int(query.get("id", [""])[0])
            except ValueError:
                idx = -1
            files = audio_files()
            if 0 <= idx < len(files):
                candidate = TRANSCRIPTS_DIR / f"{files[idx].stem}.md"
                if candidate.is_file():
                    body = candidate.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            idx = int(form.get("id", [""])[0])
        except ValueError:
            idx = -1
        files = audio_files()
        if 0 <= idx < len(files):
            audio_path = files[idx]
            cmd = ["poetry", "run", "python", "transcribe.py", str(audio_path)]
            if "force" in form:
                cmd.append("--force")
            try:
                result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=3600)
                if result.returncode != 0:
                    print(f"transcription failed for {audio_path.name}", file=sys.stderr)
                    if result.stdout.strip():
                        print(f"stdout: {result.stdout.strip()}", file=sys.stderr)
                    print(
                        f"stderr: {result.stderr.strip() or f'No stderr output (exit code {result.returncode})'}",
                        file=sys.stderr,
                    )
            except subprocess.TimeoutExpired:
                print(f"transcription timed out for {audio_path.name}", file=sys.stderr)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
