"""Autotest: genera file di prova e prova le conversioni tramite l'API di un server avviato.

Dentro il container (dove ci sono gli strumenti per creare i file di prova):
    docker compose exec converter python3 /app/selftest.py [--all] [--write-disabled]

Senza --all prova un campione rappresentativo; con --all ogni coppia sorgente -> destinazione dei campioni.
Con --write-disabled salva le conversioni fallite in WORK_DIR/disabled.json: al prossimo avvio il server
le toglie dai menu. Esce con codice 1 se almeno una conversione fallisce.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

BATCH = 50
SAMPLE_TARGETS = {
    "md": "pdf docx html pptx adoc typ", "txt": "pdf docx", "csv": "xlsx pdf json md tsv html", "html": "pdf md",
    "svg": "png pdf jpg", "docx": "pdf odt md epub jpg txt", "epub": "pdf mobi azw3 docx htmlz",
    "png": "jpg webp heic avif ico pdf gif jp2 qoi tga", "jpg": "png pdf tiff", "pdf": "txt html svg png",
    "eps": "pdf png", "mp4": "mkv webm mp3 gif mov avi wmv mpg ogv ts 3gp", "avi": "mp4",
    "wav": "mp3 flac opus ogg m4a wma ac3 aiff", "srt": "vtt ass", "json": "yaml csv xlsx", "yaml": "json",
    "toml": "json yaml csv", "ttf": "woff woff2", "zip": "7z tar.gz tar.zst", "tar.gz": "zip",
}


def sh(d: Path, *cmd: str) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=d)


def make_samples(d: Path) -> None:
    (d / "s.md").write_text("# Titolo\n\nCiao **mondo** con *corsivo* e una lista:\n\n- uno\n- due\n\n"
                            "| a | b |\n|---|---|\n| 1 | 2 |\n")
    (d / "s.txt").write_text("Riga uno\nRiga due àèìòù\n")
    (d / "s.csv").write_text("nome;eta\nAnna;30\nLuca;25\n")
    (d / "s.html").write_text("<html><body><h1>Ciao</h1><p>Paragrafo <b>forte</b></p></body></html>")
    (d / "s.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                             '<rect width="120" height="80" fill="#e5322d"/><circle cx="60" cy="40" r="25" fill="#fff"/></svg>')
    sh(d, "pandoc", "-s", "s.md", "-o", "s.docx")
    sh(d, "pandoc", "-s", "s.md", "-o", "s.epub", "--metadata", "title=Prova")
    sh(d, "magick", "-size", "320x200", "gradient:red-blue", "s.png")
    sh(d, "magick", "s.png", "s.jpg")
    sh(d, "magick", "s.png", "s.pdf")
    sh(d, "magick", "s.png", "s.eps")
    (d / "s.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nCiao mondo\n\n2\n00:00:04,000 --> 00:00:06,000\nSeconda riga\n")
    (d / "s.json").write_text('{"persone": [{"nome": "Anna", "eta": 30, "tag": ["a", "b"]}, {"nome": "Luca", "eta": 25}]}')
    (d / "s.yaml").write_text("titolo: Prova\nelementi:\n  - uno\n  - due\n")
    (d / "s.toml").write_text('titolo = "Prova"\n[[persone]]\nnome = "Anna"\n[[persone]]\nnome = "Luca"\n')
    fonts = sorted(Path("/usr/share/fonts").rglob("*.ttf"))
    if fonts:
        shutil.copy(fonts[0], d / "s.ttf")
    lavfi = ["-f", "lavfi", "-i", "testsrc=duration={0}:size=320x240:rate=25", "-f", "lavfi", "-i",
             "sine=frequency=440:duration={0}"]
    sh(d, "ffmpeg", "-v", "error", *[a.format(3) for a in lavfi], "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-shortest", "s.mp4")
    sh(d, "ffmpeg", "-v", "error", *[a.format(2) for a in lavfi], "-c:v", "mpeg4", "-c:a", "mp3", "-shortest", "s.avi")
    sh(d, "ffmpeg", "-v", "error", "-i", "s.mp4", "-vn", "-c:a", "pcm_s16le", "s.wav")
    (d / "dir").mkdir()
    (d / "dir" / "a.txt").write_text("a")
    sh(d, "bsdtar", "-a", "-cf", "s.zip", "dir")
    sh(d, "bsdtar", "-a", "-cf", "s.tar.gz", "dir")


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return json.load(r)

    def post_file(self, path: Path, target: str) -> dict:
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"target\"\r\n\r\n{target}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(self.base + "/api/jobs", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    def delete(self, job: str) -> None:
        urllib.request.urlopen(urllib.request.Request(f"{self.base}/api/jobs/{job}", method="DELETE"), timeout=30)

    def wait(self, job: str, limit: float = 600) -> dict:
        end = time.time() + limit
        while time.time() < end:
            st = self.get(f"/api/jobs/{job}")
            if st["state"] in ("done", "error"):
                return st
            time.sleep(0.5)
        return {"state": "error", "error": "tempo del test scaduto"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=os.environ.get("CONVERTER_URL", "http://127.0.0.1:8080"))
    p.add_argument("--all", action="store_true", help="prova tutte le destinazioni possibili dei campioni")
    p.add_argument("--write-disabled", action="store_true", help="salva le conversioni fallite in disabled.json")
    args = p.parse_args()

    api = Api(args.url)
    d = Path(tempfile.mkdtemp(prefix="selftest-"))
    try:
        make_samples(d)
        formats = api.get("/api/formats")["inputs"]
        pairs = []
        for f in sorted(d.glob("s.*")):
            src = f.name[2:]
            wanted = formats.get(src, []) if args.all else SAMPLE_TARGETS.get(src, "").split()
            pairs += [(f, t) for t in wanted if t in formats.get(src, [])]

        ok, failed = 0, []
        for i in range(0, len(pairs), BATCH):  # a gruppi: il server rifiuta oltre MAX_QUEUE lavori
            jobs = []
            for f, t in pairs[i:i + BATCH]:
                try:
                    jobs.append((f, t, api.post_file(f, t)["id"]))
                except Exception as e:  # noqa: BLE001
                    print(f"FAIL {f.name:10} -> {t:6} {e}")
                    failed.append([f.name[2:], t])
            for f, t, job in jobs:
                st = api.wait(job)
                if st["state"] == "done":
                    ok += 1
                    print(f"ok   {f.name:10} -> {t:6} {st['size']:>9} B  {st['out_name']}")
                else:
                    failed.append([f.name[2:], t])
                    print(f"FAIL {f.name:10} -> {t:6} {st.get('error', '')[:300]}")
                api.delete(job)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n{ok} riuscite, {len(failed)} fallite")
    if args.write_disabled:
        out = Path(os.environ.get("WORK_DIR", "/work")) / "disabled.json"
        out.write_text(json.dumps(failed))
        print(f"Scritto {out}: riavvia il servizio per applicarlo")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
