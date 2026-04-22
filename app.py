from __future__ import annotations

import html
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


AUDIO_DIR = Path("audio")
TRANSCRIPTS_DIR = Path("transcripts")


def page() -> str:
    AUDIO_DIR.mkdir(exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    rows: list[str] = []
    for mp4 in sorted(AUDIO_DIR.glob("*.mp4")):
        transcript = TRANSCRIPTS_DIR / f"{mp4.stem}.md"
        link = f'<a href="/{transcript.as_posix()}">transcript</a>' if transcript.exists() else "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(mp4.name)}</td>"
            "<td>"
            '<form method="post" action="/run">'
            f'<input type="hidden" name="file" value="{html.escape(mp4.name)}">'
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
        if self.path == "/":
            body = page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        file_path = Path(self.path.lstrip("/"))
        transcripts_root = TRANSCRIPTS_DIR.resolve()
        candidate = file_path.resolve()
        if str(candidate).startswith(str(transcripts_root) + os.sep) and candidate.is_file():
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
        file_name = Path(form.get("file", [""])[0]).name
        audio_path = AUDIO_DIR / file_name
        if audio_path.suffix == ".mp4" and audio_path.exists():
            cmd = ["poetry", "run", "python", "transcribe.py", str(audio_path)]
            if "force" in form:
                cmd.append("--force")
            subprocess.run(cmd, check=False)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
