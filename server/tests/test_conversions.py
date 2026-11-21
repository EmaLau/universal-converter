"""Sezione Conversioni (2.5): tabelle dei PDF, pagine web come articoli, trascrizione con Whisper, conversioni in blocco."""
import asyncio
import io
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from converter import options, tools, webpage
from converter.app import create_app, safe_folder
from converter.config import Settings
from converter.graph import Graph, default_graph
from converter.runner import ConvError
from converter.transcribe import Transcriber

from test_api import upper, wait

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
PDFTABLES = Path(tools.__file__).with_name("pdftables.py")


def tools_of(plan):
    return [(e.tool, e.src, e.dst) for e in plan]


# ------------------------------------------------------------------ tabelle dei PDF

def test_pdf_tables_in_graph():
    g = default_graph()
    for dst in ("csv", "xlsx", "json"):
        assert tools_of(g.plan("pdf", dst)) == [("PyMuPDF", "pdf", dst)]
    assert g.plan("pdf", "ods")[0].tool == "PyMuPDF"
    assert g.plan("pdf", "yaml") is None
    assert all(e.tool != "PyMuPDF" for e in g.plan("docx", "xlsx") or [])  # mai docx -> pdf -> tabelle


def table_pdf(path: Path):
    pymupdf = pytest.importorskip("pymupdf")
    rows = [["Nome", "Età", "Città"], ["Anna", "30", "Roma"], ["Luca", "25", "Milano"]]
    with pymupdf.open() as doc:
        page = doc.new_page()
        x0, y0, w, h = 72, 100, 120, 24
        for r in range(len(rows) + 1):
            page.draw_line((x0, y0 + r * h), (x0 + 3 * w, y0 + r * h))
        for c in range(4):
            page.draw_line((x0 + c * w, y0), (x0 + c * w, y0 + len(rows) * h))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                page.insert_text((x0 + c * w + 6, y0 + r * h + 16), cell, fontsize=11)
        doc.new_page().insert_text((72, 72), "Solo testo, nessuna tabella")
        doc.save(path)
    return rows


def test_pdftables_real(tmp_path):
    pytest.importorskip("xlsxwriter")
    pdf = tmp_path / "t.pdf"
    rows = table_pdf(pdf)
    for kind in ("csv", "json", "xlsx"):
        out = tmp_path / f"out.{kind}"
        r = subprocess.run([sys.executable, str(PDFTABLES), kind, str(pdf), str(out)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "1 tabelle" in r.stdout
        if kind == "csv":
            assert out.read_text(encoding="utf-8-sig").splitlines() == [",".join(x) for x in rows]
        elif kind == "json":
            assert json.loads(out.read_text()) == [{"page": 1, "index": 1, "rows": rows}]
        else:
            with zipfile.ZipFile(out) as z:
                assert "xl/worksheets/sheet1.xml" in z.namelist() and "Milano" in z.read("xl/sharedStrings.xml").decode()
    empty = tmp_path / "e.pdf"
    import pymupdf
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "niente tabelle")
        doc.save(empty)
    r = subprocess.run([sys.executable, str(PDFTABLES), "csv", str(empty), str(tmp_path / "x.csv")])
    assert r.returncode == 3


def test_pdf_tables_converter_messages(tmp_path, monkeypatch):
    async def none_found(cmd, **kw):
        raise ConvError("python3 ha restituito 3: nessuna tabella trovata nel PDF")

    async def two(cmd, **kw):
        return "2 tabelle"

    job = SimpleNamespace(note="", options={}, target="csv")
    monkeypatch.setattr(tools, "run", none_found)
    with pytest.raises(ConvError, match="OCR PDF"):
        asyncio.run(tools.pdf_tables(job, tmp_path / "in.pdf", "csv", tmp_path))
    monkeypatch.setattr(tools, "run", two)
    asyncio.run(tools.pdf_tables(job, tmp_path / "in.pdf", "csv", tmp_path))
    assert job.note == "2 tabelle trovate"


# ------------------------------------------------------------------ pagine web come articoli

ARTICLE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Un bel titolo - Sito di prova</title>
<script>alert(1)</script></head><body>
<nav><a href="/">Home</a> <a href="/chi">Chi siamo</a> <a href="/contatti">Contatti</a></nav>
<div class="ads">Pubblicità! Compra subito!</div>
<article><h2>Un bel titolo</h2><div class="sezione" data-x="1"><span class="mw-editsection">[modifica]</span>
<p>Questo è il primo paragrafo dell'articolo, abbastanza lungo da essere riconosciuto come contenuto principale,
con molte parole, virgole, e frasi che continuano. Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>
<p><img src="/img.png" alt="figura uno" onerror="alert(2)"></p>
<p>Secondo paragrafo, anche questo lungo: sed do eiusmod tempor incididunt ut labore et dolore magna aliqua,
ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>
<p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" data-src="/lazy.png" alt="pigra"></p>
<p><img src="/manca.png" alt="non esiste"> <a href="/altro">un link relativo</a></p>
</div></article><footer>Copyright</footer></body></html>"""


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        files = {"/pagina": ("text/html; charset=utf-8", ARTICLE.encode()), "/img.png": ("image/png", PNG),
                 "/lazy.png": ("image/png", PNG)}
        if self.path not in files:
            self.send_response(404)
            self.end_headers()
            return
        ctype, body = files[self.path]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def site():
    srv = HTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_article(site):
    pytest.importorskip("readability")
    title, page = webpage.article(ARTICLE.encode(), site + "/pagina", allow_private=True)
    assert title == "Un bel titolo"
    assert f'<h1>Un bel titolo</h1>' in page and f'href="{site}/pagina"' in page
    assert "primo paragrafo" in page and "Secondo paragrafo" in page
    assert "alert" not in page and "<script" not in page and "onerror" not in page
    assert "Chi siamo" not in page and "Compra subito" not in page
    assert page.count('src="data:image/png;base64,') == 2  # l'immagine e quella "pigra"
    assert f'data-orig="{site}/img.png"' in page and f'data-orig="{site}/lazy.png"' in page
    assert "non esiste" not in page  # immagine che non si scarica: tolta
    assert f'href="{site}/altro"' in page  # link resi assoluti
    assert "[modifica]" not in page and "data-x" not in page and "class=" not in page
    body = page.split("</a></p>", 1)[1]
    assert "<div" not in body and "<span" not in body  # contenitori tolti: Markdown pulito
    assert page.count("<h1>") == 1 and "<h2>Un bel titolo" not in page  # titolo non ripetuto
    restored = webpage.restore_image_urls(page)
    assert "data:image" not in restored and f'src="{site}/img.png"' in restored and "data-orig" not in restored


def test_article_images_respect_private_network(site):
    pytest.importorskip("readability")
    _, page = webpage.article(ARTICLE.encode(), site + "/pagina", allow_private=False)
    assert "data:image" not in page and "<img" not in page


def test_fetch_article_api(tmp_path, site):
    pytest.importorskip("readability")
    g = Graph()
    g.add("html", "md", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, url_allow_private=True), g)) as c:
        raw = c.post("/api/fetch", data={"url": site + "/pagina"}).json()
        assert raw["filename"] == "pagina.html" and raw["ext"] == "html"
        art = c.post("/api/fetch", data={"url": site + "/pagina", "article": "true"}).json()
        assert art["filename"] == "Un bel titolo.html" and art["targets"] == ["md"]


def test_pandoc_restores_image_urls_for_text(tmp_path, monkeypatch):
    seen = []

    async def fake_run(cmd, **kw):
        seen.append(Path(cmd[-1]).read_text())
        return ""

    monkeypatch.setattr(tools, "run", fake_run)
    inp = tmp_path / "input.html"
    inp.write_text('<p><img src="data:image/png;base64,AAAA" data-orig="https://x.org/a.png"></p>')
    for out_ext, has_data in (("md", False), ("docx", True)):
        wd = tmp_path / out_ext
        wd.mkdir()
        asyncio.run(tools.pandoc(None, inp, out_ext, wd))
        assert ("data:image" in seen[-1]) is has_data
        assert has_data or 'src="https://x.org/a.png"' in seen[-1]


# ------------------------------------------------------------------ trascrizione (Whisper)

class Whisper(BaseHTTPRequestHandler):
    seen: list = []
    reply = (200, "text/plain", "1\n00:00:00,000 --> 00:00:02,000\nCiao a tutti\n")

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Whisper.seen.append((self.path, self.headers.get("Authorization"), body))
        status, ctype, text = Whisper.reply
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(text.encode())


@pytest.fixture
def whisper():
    srv = HTTPServer(("127.0.0.1", 0), Whisper)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Whisper.seen = []
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_transcription_in_graph():
    t = Transcriber("http://whisper:8000")
    g = default_graph(transcriber=t)
    assert tools_of(g.plan("mp4", "srt")) == [("Whisper", "mp4", "srt")]
    assert tools_of(g.plan("ogg", "txt")) == [("Whisper", "ogg", "txt")]
    assert g.plan("mp3", "docx") is None
    assert options.applicable(g.plan("mov", "vtt"), "vtt") == ["language"]
    assert options.parse({"language": "it"}, g.plan("mov", "vtt"), "vtt") == {"language": "it"}
    assert default_graph().plan("mp4", "srt") is None  # senza WHISPER_URL niente trascrizioni
    assert "Whisper" in g.payload()["tools"] and "srt" in g.payload()["inputs"]["mp4"]
    with pytest.raises(ValueError):
        Transcriber("ftp://x")


def test_transcriber_post(tmp_path, whisper):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3fakeaudio")
    t = Transcriber(whisper, "Systran/faster-whisper-small", "segreto")
    assert t.post(audio, "srt", "it").startswith("1\n00:00:00,000")
    path, auth, body = Whisper.seen[-1]
    assert path == "/v1/audio/transcriptions" and auth == "Bearer segreto"
    for part in (b'name="response_format"\r\n\r\nsrt', b'name="language"\r\n\r\nit',
                 b'name="model"\r\n\r\nSystran/faster-whisper-small', b'filename="audio.mp3"', b"ID3fakeaudio"):
        assert part in body
    Whisper.reply = (200, "application/json", '{"text": "testo semplice"}')
    assert Transcriber(whisper + "/v1/audio/transcriptions").post(audio, "text") == "testo semplice"
    Whisper.reply = (500, "text/plain", "modello non trovato")
    with pytest.raises(ConvError, match="500: modello non trovato"):
        t.post(audio, "text")
    Whisper.reply = (200, "text/plain", "1\n00:00:00,000 --> 00:00:02,000\nCiao a tutti\n")
    with pytest.raises(ConvError, match="non raggiungibile"):
        Transcriber("http://127.0.0.1:9").post(audio, "text")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="serve ffmpeg")
def test_transcriber_end_to_end(tmp_path, whisper):
    wav = tmp_path / "in.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", str(wav)], check=True)
    job = SimpleNamespace(options={"language": "en"}, target="srt", step="", note="")
    out = asyncio.run(Transcriber(whisper)(job, wav, "srt", tmp_path))
    assert "Ciao a tutti" in out.read_text() and b'name="language"\r\n\r\nen' in Whisper.seen[-1][2]


# ------------------------------------------------------------------ conversioni in blocco

def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


async def broken(job, inp, out_ext, wd):
    raise ConvError(f"rotto apposta: {inp}")


@pytest.fixture
def batch_client(tmp_path):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.add("rst", "md", broken, "Broken")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path), g)) as c:
        yield c


def test_batch_in_graph_and_formats():
    g = default_graph()
    assert g.is_batch("zip", "pdf") and g.is_batch("tar.gz", "jpg") and g.is_batch("7z", "mp3")
    assert not g.is_batch("zip", "7z") and not g.is_batch("pdf", "jpg") and not g.is_batch("zip", "ttf")
    assert g.plan("zip", "pdf") is None  # non e' un percorso: lo gestisce la conversione in blocco
    batch = g.payload()["batch"]
    assert "zip" in batch["archives"] and "pdf" in batch["targets"] and "zip" not in batch["targets"]


@pytest.mark.skipif(not shutil.which("bsdtar"), reason="serve bsdtar (libarchive-tools)")
def test_batch_conversion(batch_client):
    c = batch_client
    assert c.get("/api/formats").json()["batch"] == {"archives": ["zip", "7z", "rar", "tar", "tar.gz", "tar.xz",
                                                                  "tar.bz2", "tar.zst"], "targets": ["md"]}
    data = make_zip({"a.txt": b"uno", "cartella/b.TXT": b"due", "cartella/sotto/c.md": b"gia' md",
                     "foto.png": PNG, "rotto.rst": b"x", ".nascosto.txt": b"no",
                     # il bsdtar di macOS legge __MACOSX come metadati Apple e rifiuta quelli finti
                     **({} if sys.platform == "darwin" else {"__MACOSX/a.txt": b"no"})})
    r = c.post("/api/jobs", data={"target": "md"}, files={"file": ("appunti.zip", data)})
    assert r.status_code == 201, r.text
    st = wait(c, r.json()["id"])
    assert st["state"] == "done", st["error"]
    assert st["out_name"] == "appunti-md.zip"
    assert st["note"] == "2 convertiti, 1 copiati, 1 saltati, 1 non riusciti"
    with zipfile.ZipFile(io.BytesIO(c.get(f"/api/jobs/{st['id']}/download").content)) as z:
        names = {n.removeprefix("./") for n in z.namelist() if not n.endswith("/")}
        assert names == {"a.md", "cartella/b.md", "cartella/sotto/c.md", "resoconto-conversione.txt"}
        assert z.read("./a.md" if "./a.md" in z.namelist() else "a.md") == b"UNO"
        report = z.read(next(n for n in z.namelist() if n.endswith("resoconto-conversione.txt"))).decode()
        assert "foto.png" in report and "rotto.rst: rotto apposta" in report and "/jobs/" not in report
    en = c.post("/api/jobs", data={"target": "md"}, files={"file": ("x.zip", data)}, headers={"Accept-Language": "en"})
    st = wait(c, en.json()["id"])
    assert c.get(f"/api/jobs/{st['id']}", headers={"Accept-Language": "en"}).json()["note"] == \
        "2 converted, 1 copied, 1 skipped, 1 failed"
    # niente da convertire: errore chiaro
    r = c.post("/api/jobs", data={"target": "md"}, files={"file": ("foto.zip", make_zip({"a.png": PNG}))})
    st = wait(c, r.json()["id"])
    assert st["state"] == "error" and "nessun file" in st["error"]
    # le opzioni non valgono per le conversioni in blocco; gli altri formati restano rifiutati
    assert c.post("/api/jobs", data={"target": "md", "options": '{"quality": 5}'},
                  files={"file": ("a.zip", data)}).status_code == 400
    assert c.post("/api/jobs", data={"target": "pdf"}, files={"file": ("a.zip", data)}).status_code == 400


def test_safe_folder():
    assert safe_folder("Foto/2026/estate") == "Foto/2026/estate"
    assert safe_folder("../../etc") == "etc"
    assert safe_folder("/assoluto/x") == "assoluto/x"
    assert safe_folder(".git/hooks") == "hooks"
    assert safe_folder("a\\b") == "a/b"
    assert safe_folder(None) == "" and safe_folder(["x"]) == ""
    assert safe_folder("/".join("abcdefghijkl")) == "/".join("abcdefghij")


def test_results_zip_with_folders(batch_client):
    c = batch_client
    ids = []
    for name in ("a.txt", "a.txt", "b.txt"):
        r = c.post("/api/jobs", data={"target": "md"}, files={"file": (name, b"x")})
        ids.append(wait(c, r.json()["id"])["id"])
    paths = json.dumps({ids[0]: "Corso/Lezioni", ids[1]: "../../fuori", ids[2]: ""})
    r = c.post("/api/jobs/zip", data={"ids": ",".join(ids), "paths": paths})
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(z.namelist()) == ["Corso/Lezioni/a.md", "b.md", "fuori/a.md"]
    r = c.post("/api/jobs/zip", data={"ids": ",".join(ids), "paths": "non json"})
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(z.namelist()) == ["a (2).md", "a.md", "b.md"]
