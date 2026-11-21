"""Autotest: genera file di prova e prova le conversioni tramite l'API di un server avviato.

Dentro il container (dove ci sono gli strumenti per creare i file di prova):
    docker compose exec converter python3 /app/selftest.py [--all] [--write-disabled]

Senza --all prova un campione rappresentativo; con --all ogni coppia sorgente -> destinazione dei campioni.
Prova anche gli strumenti PDF disponibili (unire, dividere, estrarre, togliere, ruotare, comprimere, OCR),
alcune conversioni con le opzioni (qualita', dimensione, taglio, pagine, impaginazione delle slide),
le tabelle di un PDF, una conversione in blocco (ZIP -> ZIP) e le anteprime dei risultati.
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


def make_table_pdf(path: Path) -> None:
    """PDF con una tabella a righe e colonne disegnate (per PDF -> CSV/XLSX/JSON)."""
    import pymupdf
    rows = [["Nome", "Eta", "Citta"], ["Anna", "30", "Roma"], ["Luca", "25", "Milano"]]
    with pymupdf.open() as doc:
        page = doc.new_page()
        for r in range(len(rows) + 1):
            page.draw_line((72, 100 + r * 24), (432, 100 + r * 24))
        for c in range(4):
            page.draw_line((72 + c * 120, 100), (72 + c * 120, 172))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                page.insert_text((78 + c * 120, 116 + r * 24), cell, fontsize=11)
        doc.save(path)


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
    # slide vere (testo selezionabile, pagine 16:9) per PDF -> Word/PowerPoint
    sh(d, "pandoc", "s.md", "-o", "slide.pptx")
    sh(d, "soffice", f"-env:UserInstallation={(d / 'lo').as_uri()}", "--headless", "--convert-to", "pdf", "slide.pptx")
    sh(d, "magick", "-size", "320x200", "gradient:red-blue", "s.png")
    make_table_pdf(d / "tabella.pdf")
    sh(d, "magick", "s.png", "s.jpg")
    sh(d, "magick", "s.png", "s.pdf")
    sh(d, "magick", "s.png", "s.eps")
    sh(d, "magick", "-size", "800x400", "xc:white", "-pointsize", "48", "-annotate", "+40+200", "Testo da riconoscere",
       "scan.pdf")  # una "scansione": solo immagine, niente testo
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
    # conversione in blocco: documenti e un'immagine in PDF, l'audio va saltato
    (d / "lotto").mkdir()
    for f in ("s.md", "s.txt", "s.png", "s.wav"):
        shutil.copy(d / f, d / "lotto" / f)
    sh(d, "bsdtar", "-a", "-cf", "lotto.zip", "lotto")


class Api:
    def __init__(self, base: str, key: str = ""):
        self.base = base.rstrip("/")
        self.auth = {"apikey": key} if key else {}  # chiave con i permessi formats, convert e jobs

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=self.auth), timeout=30) as r:
            return json.load(r)

    def post(self, url: str, fields: dict[str, str], files: list[tuple[str, Path]]) -> dict:
        b = uuid.uuid4().hex
        body = b"".join(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                        for k, v in fields.items())
        for name, path in files:
            body += (f"--{b}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\n"
                     "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(self.base + url, body, {"Content-Type": f"multipart/form-data; boundary={b}", **self.auth})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    def post_file(self, path: Path, target: str) -> dict:
        return self.post("/api/jobs", {"target": target}, [("file", path)])

    def delete(self, job: str) -> None:
        urllib.request.urlopen(urllib.request.Request(f"{self.base}/api/jobs/{job}", method="DELETE", headers=self.auth), timeout=30)

    def wait(self, job: str, limit: float = 600) -> dict:
        end = time.time() + limit
        while time.time() < end:
            st = self.get(f"/api/jobs/{job}")
            if st["state"] in ("done", "error"):
                return st
            time.sleep(0.5)
        return {"state": "error", "error": "tempo del test scaduto"}


def pdf_cases(d: Path) -> list[tuple[str, dict, list[Path]]]:
    one, scan = d / "s.pdf", d / "scan.pdf"
    three = d / "tre.pdf"
    sh(d, "qpdf", "--empty", "--pages", "s.pdf", "s.pdf", "scan.pdf", "--", "tre.pdf")
    return [("merge", {}, [one, scan]), ("split", {}, [three]), ("split", {"pages": "1-2, 3"}, [three]),
            ("extract", {"pages": "2-"}, [three]), ("remove", {"pages": "1"}, [three]),
            ("rotate", {"angle": "90", "pages": "1"}, [three]), ("compress", {"level": "high"}, [three]),
            ("ocr", {"lang": "ita+eng"}, [scan])]


def run_pdf_tools(api: Api, d: Path) -> tuple[int, list]:
    available = {t["name"] for t in api.get("/api/pdf")["tools"]}
    ok, failed = 0, []
    for tool, opts, files in pdf_cases(d):
        if tool not in available:
            print(f"--   pdf {tool:8} non disponibile su questo server")
            continue
        label = f"pdf {tool:8} {' '.join(f'{k}={v}' for k, v in opts.items())}"
        try:
            st = api.wait(api.post(f"/api/pdf/{tool}", opts, [("files", f) for f in files])["id"])
        except Exception as e:  # noqa: BLE001
            st = {"state": "error", "error": str(e)}
        if st["state"] == "done":
            ok += 1
            print(f"ok   {label:32} {st['size']:>9} B  {st['out_name']}  {st.get('note', '')}")
            api.delete(st["id"])
        else:
            failed.append(["pdf", tool])
            print(f"FAIL {label:32} {st.get('error', '')[:300]}")
    return ok, failed


def option_cases(d: Path) -> list[tuple[Path, str, dict]]:
    return [(d / "s.png", "jpg", {"quality": 70, "max_size": 160, "strip": True}),
            (d / "s.jpg", "jpg", {"max_size": 100}),
            (d / "s.mp4", "mp4", {"start": "1", "height": "360", "video_quality": "low", "audio_bitrate": "96"}),
            (d / "s.mp4", "gif", {"end": "1.5", "height": "360"}),
            (d / "s.wav", "mp3", {"end": "2", "audio_bitrate": "64", "mono": True}),
            (d / "tre.pdf", "png", {"pages": "2-3", "dpi": "72"}),
            (d / "slide.pdf", "docx", {}), (d / "slide.pdf", "docx", {"layout": "exact"}),
            (d / "slide.pdf", "pptx", {}), (d / "slide.pdf", "pptx", {"layout": "exact"}),
            (d / "tabella.pdf", "xlsx", {}), (d / "tabella.pdf", "csv", {}),
            (d / "lotto.zip", "pdf", {}),
            (d / "s.docx", "pdf", {}), (d / "s.md", "html", {}), (d / "s.avi", "avi", {})]


def run_options(api: Api, d: Path) -> tuple[int, list]:
    """Conversioni con le opzioni e anteprima di ogni risultato (se il server le ha)."""
    ok, failed = 0, []
    for f, target, opts in option_cases(d):
        label = f"{f.name:8} -> {target:4} {json.dumps(opts)[:40]}"
        if not f.exists():
            continue
        try:
            fields = {"target": target, **({"options": json.dumps(opts)} if opts else {})}
            st = api.wait(api.post("/api/jobs", fields, [("file", f)])["id"])
            kind = ""
            if st["state"] == "done" and st.get("preview"):
                req = urllib.request.Request(f"{api.base}/api/jobs/{st['id']}/preview", headers=api.auth)
                with urllib.request.urlopen(req, timeout=600) as r:
                    kind = f"anteprima {st['preview']} {len(r.read())} B"
        except Exception as e:  # noqa: BLE001
            st = {"state": "error", "error": str(e)}
        if st["state"] == "done":
            ok += 1
            print(f"ok   {label:52} {st['size']:>9} B  {kind}  {st.get('note', '')}")
            api.delete(st["id"])
        else:
            failed.append([f.name, target])
            print(f"FAIL {label:52} {st.get('error', '')[:300]}")
    return ok, failed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=os.environ.get("CONVERTER_URL", "http://127.0.0.1:8080"))
    p.add_argument("--key", default=os.environ.get("CONVERTER_API_KEY", ""),
                   help="chiave API, se nella pagina /admin la chiave e' obbligatoria")
    p.add_argument("--all", action="store_true", help="prova tutte le destinazioni possibili dei campioni")
    p.add_argument("--write-disabled", action="store_true", help="salva le conversioni fallite in disabled.json")
    args = p.parse_args()

    api = Api(args.url, args.key)
    d = Path(tempfile.mkdtemp(prefix="selftest-"))
    pdf_failed: list = []
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
        pdf_ok, pdf_failed = run_pdf_tools(api, d)
        ok += pdf_ok
        opt_ok, opt_failed = run_options(api, d)
        ok += opt_ok
        pdf_failed += opt_failed
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n{ok} riuscite, {len(failed) + len(pdf_failed)} fallite")
    if args.write_disabled:
        out = Path(os.environ.get("WORK_DIR", "/work")) / "disabled.json"
        out.write_text(json.dumps(failed))
        print(f"Scritto {out}: riavvia il servizio per applicarlo")
    return 1 if failed or pdf_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
