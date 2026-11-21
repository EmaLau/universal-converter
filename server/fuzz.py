"""Prova con file malformati: un file costruito apposta non deve far cadere il servizio.

Genera file rotti o "bombe" (PDF troncati e con cicli, immagini che dichiarano dimensioni enormi, SVG con entita'
annidate, archivi che si espandono a 1 GB, JSON annidato all'infinito, byte casuali con estensioni note), li manda
all'API di un server avviato e controlla che:
  - ogni lavoro finisca (done o error) entro il tempo massimo, senza restare appeso;
  - il servizio risponda ancora a /healthz dopo ogni caso e alla fine.

Non servono programmi esterni: solo la libreria standard. Esce con codice 1 se un controllo fallisce.
    python3 fuzz.py [--url http://127.0.0.1:8080] [--key uconv_...] [--timeout 600]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import zlib


def png_header_bomb(w: int = 60000, h: int = 60000) -> bytes:
    """PNG che dichiara w x h pixel (oltre 3 miliardi) con pochi byte di dati compressi."""
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    row = b"\x00" + b"\x00" * (w * 3)
    comp = zlib.compressobj(9)
    data = b"".join(comp.compress(row) for _ in range(64)) + comp.flush()  # solo le prime righe: file piccolo
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", data) + chunk(b"IEND", b""))


def svg_laughs(levels: int = 10) -> bytes:
    """"Billion laughs": entita' XML che si espandono a miliardi di caratteri."""
    ents = ['<!ENTITY l0 "lol">'] + [f'<!ENTITY l{i} "{("&l%d;" % (i - 1)) * 10}">' for i in range(1, levels)]
    return (f'<?xml version="1.0"?><!DOCTYPE svg [{"".join(ents)}]>'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><text y="20">&l{levels - 1};</text></svg>').encode()


def zip_bomb(size_mb: int = 1024) -> bytes:
    """ZIP piccolo (circa 1 MB) che contiene un file di zeri da size_mb MB."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        with z.open("zeros.bin", "w", force_zip64=True) as f:
            block = b"\x00" * (1024 * 1024)
            for _ in range(size_mb):
                f.write(block)
    return buf.getvalue()


def many_files(n: int) -> bytes:
    """ZIP con tanti file piccolissimi (oltre il limite delle conversioni in blocco)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(n):
            z.writestr(f"f{i}.txt", "x")
    return buf.getvalue()


def pdf_page_loop() -> bytes:
    """PDF il cui albero delle pagine contiene se stesso."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [2 0 R 3 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()


def pdf_huge_page() -> bytes:
    """PDF valido con una pagina di 14.400 x 14.400 punti (il caso che faceva cadere Plico)."""
    return pdf_page_loop().replace(b"/Kids [2 0 R 3 0 R] /Count 2", b"/Kids [3 0 R] /Count 1").replace(
        b"[0 0 612 792]", b"[0 0 14400 14400]")


def cases() -> list[tuple]:
    """(nome, contenuto, formato di arrivo[, opzioni])."""
    rnd = os.urandom(256 * 1024)
    good_pdf = pdf_huge_page()
    return [
        ("random.docx", rnd, "pdf"),
        ("random.pdf", rnd, "txt"),
        ("random.png", rnd, "jpg"),
        ("random.mp4", rnd, "mp3"),
        ("random.epub", rnd, "pdf"),
        ("random.zip", rnd, "7z"),
        ("random.heic", rnd, "jpg"),
        ("truncated.pdf", good_pdf[: len(good_pdf) // 2], "png"),
        ("page-loop.pdf", pdf_page_loop(), "png"),
        ("page-loop-text.pdf", pdf_page_loop(), "txt"),
        ("huge-page.pdf", good_pdf, "jpg"),
        ("png-bomb.png", png_header_bomb(), "webp"),
        ("png-bomb-pdf.png", png_header_bomb(), "pdf"),
        ("laughs.svg", svg_laughs(), "png"),
        ("zip-bomb.zip", zip_bomb(), "tar.gz"),
        ("nested.json", b"[" * 200000 + b"]" * 200000, "yaml"),
        ("nested-csv.json", json.dumps({"a": [[[[[1]]]]] * 1000}).encode(), "csv"),
        ("empty-ish.md", b"\x00" * 10, "pdf"),
        # 2.5: pagine come immagini, tabelle, slide, conversioni in blocco
        ("huge-page-exact.pdf", good_pdf, "docx", {"layout": "exact"}),
        ("page-loop-tables.pdf", pdf_page_loop(), "xlsx"),
        ("random-tables.pdf", rnd, "csv"),
        ("page-loop-slides.pdf", pdf_page_loop(), "pptx"),
        ("zip-bomb-batch.zip", zip_bomb(), "pdf"),
        ("random-batch.zip", rnd, "pdf"),
        ("many-files-batch.zip", many_files(2500), "md"),
        # 2.6: email, Graphviz, sottotitoli dai video, CSV per foglio, scansioni con OCR automatico
        ("random.eml", rnd, "pdf"),
        ("random.msg", rnd, "pdf"),
        ("random-attachments.msg", rnd, "zip"),
        ("random.gv", rnd, "svg"),
        ("include.gv", b'digraph { a [image="/etc/passwd"]; b [shapefile="/etc/shadow"]; a -> b }', "png"),
        ("random-subs.mkv", rnd, "srt"),
        ("random-sheets.ods", rnd, "csv"),
        ("page-loop-ocr.pdf", pdf_page_loop(), "docx"),
    ]


class Client:
    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key

    def req(self, method: str, path: str, data: bytes | None = None, ctype: str | None = None, timeout: int = 120):
        r = urllib.request.Request(self.url + path, data=data, method=method)
        if self.key:
            r.add_header("apikey", self.key)
        if ctype:
            r.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def submit(self, name: str, body: bytes, target: str, opts: dict | None = None):
        b = uuid.uuid4().hex
        extra = f'--{b}\r\nContent-Disposition: form-data; name="options"\r\n\r\n{json.dumps(opts)}\r\n' if opts else ""
        parts = (f'--{b}\r\nContent-Disposition: form-data; name="target"\r\n\r\n{target}\r\n{extra}'
                 f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                 'Content-Type: application/octet-stream\r\n\r\n').encode() + body + f"\r\n--{b}--\r\n".encode()
        return self.req("POST", "/api/jobs", parts, f"multipart/form-data; boundary={b}")

    def healthy(self) -> bool:
        try:
            return self.req("GET", "/healthz", timeout=15)[1].get("ok") is True
        except OSError:
            return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--key", default=os.environ.get("CONVERTER_API_KEY", ""))
    ap.add_argument("--timeout", type=int, default=600, help="secondi massimi per ogni lavoro")
    a = ap.parse_args()
    c, failures = Client(a.url, a.key), 0
    if not c.healthy():
        print("Il server non risponde su", a.url)
        return 1
    for name, body, target, *opts in cases():
        t0 = time.time()
        code, job = c.submit(name, body, target, opts[0] if opts else None)
        if code != 201:  # rifiutato subito (formato non supportato, conversione disattivata...): va bene
            print(f"ok   {name:22} -> {target:6} rifiutato ({code}): {str(job.get('detail', ''))[:80]}")
        else:
            state = job.get("state")
            while state in ("queued", "running") and time.time() - t0 < a.timeout:
                time.sleep(2)
                _, job = c.req("GET", f"/api/jobs/{job['id']}")
                state = job.get("state")
            took = time.time() - t0
            if state in ("queued", "running"):
                failures += 1
                print(f"FAIL {name:22} -> {target:6} ancora '{state}' dopo {took:.0f} s")
            else:
                detail = job.get("error") or job.get("out_name") or ""
                print(f"ok   {name:22} -> {target:6} {state:5} in {took:4.0f} s  {str(detail)[:90]}")
                c.req("DELETE", f"/api/jobs/{job['id']}")
        if not c.healthy():
            failures += 1
            print(f"FAIL il servizio non risponde piu' dopo {name}")
            for _ in range(30):  # aspetta un eventuale riavvio del container
                time.sleep(2)
                if c.healthy():
                    break
    print(f"\n{len(cases())} casi, {failures} problemi")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
