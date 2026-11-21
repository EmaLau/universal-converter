"""2.6: qualita' dei risultati (OCR automatico, controllo delle pagine, caratteri, sottotitoli, CSV per foglio,
Graphviz, email) e manutenzione (limite di memoria, Pandoc senza rete, lavori che sopravvivono al riavvio)."""
import asyncio
import io
import json
import subprocess
import sys
import time
import zipfile
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from converter import emailconv, i18n, options, runner, tools
from converter.app import create_app
from converter.config import Settings
from converter.formats import is_graphviz
from converter.graph import Graph, default_graph
from converter.runner import ConvError

from test_api import slow, upper, wait

EMAILCONV = Path(tools.__file__).with_name("emailconv.py")
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def job_ns(**kw):
    return SimpleNamespace(**{"note": "", "options": {}, "target": "docx", "step": "", "lang": "it",
                              "extras": {}, "dir": kw.pop("dir", Path("/tmp")), **kw})


# ------------------------------------------------------------------ note, limiti, Pandoc senza rete

def test_notes_join_and_translate():
    job = job_ns()
    tools.add_note(job, tools.OCR_NOTE)
    tools.add_note(job, "3 tabelle trovate")
    assert job.note == "era una scansione: testo riconosciuto con l'OCR; 3 tabelle trovate"
    assert i18n.t(job.note, "en") == "it was a scan: text recognised with OCR; 3 tables found"


def test_memory_limit_only_where_asked(monkeypatch):
    seen = []

    class Proc:
        returncode, pid, stdout = 0, 1, None

        async def wait(self):
            return 0

    async def fake_exec(*cmd, **kw):
        seen.append(cmd)
        p = Proc()

        class Out:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration
        p.stdout = Out()
        return p

    monkeypatch.setattr(runner, "_PRLIMIT", "/usr/bin/prlimit")
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    runner.set_file_size_limit(1000)
    runner.set_memory_limit(3 * 1024**3)
    try:
        asyncio.run(runner.run(["soffice", "x"]))
        asyncio.run(runner.run(["python3", "x"], limit_memory=True))
    finally:
        runner.set_file_size_limit(0)
        runner.set_memory_limit(0)
    assert seen[0][:3] == ("/usr/bin/prlimit", "--fsize=1000", "--")
    assert seen[1][:4] == ("/usr/bin/prlimit", "--fsize=1000", f"--as={3 * 1024**3}", "--")


def test_pandoc_without_network(tmp_path, monkeypatch):
    seen = {}

    async def fake_run(cmd, **kw):
        seen.update(kw.get("env") or {})
        return ""

    monkeypatch.setattr(tools, "run", fake_run)
    inp = tmp_path / "input.md"
    inp.write_text("![](http://192.168.1.1/admin.png)")
    asyncio.run(tools.pandoc(None, inp, "docx", tmp_path))
    assert seen["http_proxy"] == seen["HTTPS_PROXY"] == "http://127.0.0.1:9" and seen["no_proxy"] == ""


def test_fonts_conf_is_valid():
    paths = [Path(tools.__file__).parents[1] / "fonts.conf", Path("/etc/fonts/conf.d/60-universal-converter.conf")]
    conf = next((p for p in paths if p.exists()), None)  # nel repository o nell'immagine
    if conf is None:
        pytest.skip("fonts.conf non trovato")
    root = ElementTree.parse(conf).getroot()
    pairs = {a.find("family").text: a.find("accept/family").text for a in root.findall("alias")}
    assert pairs["Gill Sans MT"] == "Gillius ADF" and pairs["Calibri"] == "Carlito"
    assert pairs["Century Gothic"] == "URW Gothic" and pairs["Garamond"] == "EB Garamond"


# ------------------------------------------------------------------ OCR automatico e controllo delle pagine

def scripted_run(answers, calls):
    async def fake_run(cmd, **kw):
        calls.append(cmd)
        for key, value in answers.items():
            if key in cmd[0] or key in " ".join(cmd):
                if isinstance(value, Exception):
                    raise value
                if callable(value):
                    return value(cmd)
                return value
        return ""
    return fake_run


def test_scans_get_ocr(tmp_path, monkeypatch):
    calls = []

    def ocr(cmd):
        Path(cmd[-1]).write_bytes(b"%PDF ocr")
        return ""

    monkeypatch.setattr(tools, "run", scripted_run({"pdfinfo": "Pages: 3\n", "pdftotext": "  \n\x0c \n",
                                                    "ocrmypdf": ocr}, calls))
    monkeypatch.setattr(tools.shutil, "which", lambda name: "/usr/bin/" + name)
    job = job_ns()
    out = asyncio.run(tools.ocr_if_scan(job, tmp_path / "in.pdf", tmp_path))
    assert out == tmp_path / "ocr.pdf" and job.note == tools.OCR_NOTE
    assert next(c for c in calls if c[0] == "ocrmypdf")[:4] == ["ocrmypdf", "-q", "-l", "ita+eng"]
    # PDF con testo: nessun OCR
    calls.clear()
    monkeypatch.setattr(tools, "run", scripted_run({"pdfinfo": "Pages: 1\n", "pdftotext": "Testo vero " * 10}, calls))
    job = job_ns()
    assert asyncio.run(tools.ocr_if_scan(job, tmp_path / "in.pdf", tmp_path)) == tmp_path / "in.pdf"
    assert job.note == "" and not any(c[0] == "ocrmypdf" for c in calls)
    # spento con AUTO_OCR=false
    tools.configure(auto_ocr=False)
    try:
        monkeypatch.setattr(tools, "run", scripted_run({"pdfinfo": "Pages: 3\n", "pdftotext": ""}, calls))
        assert asyncio.run(tools.ocr_if_scan(job_ns(), tmp_path / "in.pdf", tmp_path)) == tmp_path / "in.pdf"
    finally:
        tools.configure()


def test_pages_check(tmp_path, monkeypatch):
    assert tools.pages_differ(9, 17) and tools.pages_differ(2, 4) and not tools.pages_differ(10, 11)
    assert not tools.pages_differ(0, 5) and not tools.pages_differ(1, 2)
    docx = tmp_path / "w.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("docProps/app.xml", "<Properties><Pages>12</Pages></Properties>")
    assert tools.docx_saved_pages(docx) == 12 and tools.docx_saved_pages(tmp_path / "nope.docx") == 0
    counts = iter([9, 17])

    async def pages(p):
        return next(counts)

    async def lo(job, inp, out_ext, wd, infilter=None):
        out = wd / "check.pdf"
        out.write_bytes(b"%PDF")
        return out

    monkeypatch.setattr(tools, "pdf_page_count", pages)
    monkeypatch.setattr(tools, "libreoffice", lo)
    job = job_ns()
    asyncio.run(tools.check_pages(job, tmp_path / "in.pdf", docx, tmp_path))
    assert job.note == "il PDF ha 9 pagine, il Word se ne impagina 17: prova Impaginazione «Identica»"
    assert "Layout “Identical”" in i18n.t(job.note, "en")


# ------------------------------------------------------------------ CSV con un file per foglio

def test_all_sheets_to_csv(tmp_path, monkeypatch):
    seen = []

    def soffice(names):
        def make(cmd):
            seen.append(cmd)
            for n in names:
                (tmp_path / n).write_text("a,b\n")
            return ""
        return make

    for names, final, expect in ((["input-Foglio1.csv", "input-Dati.csv"], True, "zip"),
                                 (["input-Foglio1.csv"], True, "csv"), (["input.csv"], False, "csv")):
        for f in tmp_path.glob("*"):
            f.unlink()
        monkeypatch.setattr(tools, "run", scripted_run({"soffice": soffice(names)}, []))
        job = job_ns(target="csv" if final else "json", dir=tmp_path)
        out = asyncio.run(tools.libreoffice(job, tmp_path / "input.xlsx", "csv", tmp_path))
        assert out.suffix == "." + expect
        assert seen[-1][seen[-1].index("--convert-to") + 1].endswith(",-1") is final
        if expect == "zip":
            assert sorted(zipfile.ZipFile(out).namelist()) == ["Dati.csv", "Foglio1.csv"]
            assert job.note == "2 fogli, un CSV per foglio"


# ------------------------------------------------------------------ sottotitoli

def test_subtitle_tracks_and_text(monkeypatch):
    probe = json.dumps({"streams": [{"codec_name": "hdmv_pgs_subtitle"}, {"codec_name": "subrip", "tags": {"language": "ita"}},
                                    {"codec_name": "mov_text"}]})
    monkeypatch.setattr(tools, "run", scripted_run({"ffprobe": probe}, []))
    assert asyncio.run(tools.subtitle_tracks(Path("v.mkv"))) == [(1, "ita"), (2, "")]
    assert tools.srt_to_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Ciao</i>\n\n2\n00:00:03,000 --> 00:00:04,000\n"
                             "{\\an8}a tutti\n") == "Ciao\na tutti\n"


def test_video_subtitles(tmp_path, monkeypatch):
    calls = []

    def ffmpeg(cmd):
        Path(cmd[-1]).write_text("1\n00:00:01,000 --> 00:00:02,000\nCiao\n")
        return ""

    probe = json.dumps({"streams": [{"codec_name": "subrip", "tags": {"language": "ita"}}, {"codec_name": "ass"}]})
    monkeypatch.setattr(tools, "run", scripted_run({"ffprobe": probe, "ffmpeg": ffmpeg}, calls))
    job = job_ns(target="txt")
    out = asyncio.run(tools.video_subtitles()(job, tmp_path / "v.mkv", "txt", tmp_path))
    assert out.read_text() == "Ciao\n" and job.note == "sottotitoli presi dal video (ita) [1/2]"
    assert ["-map", "0:s:0"] == calls[1][calls[1].index("-map"):calls[1].index("-map") + 2]
    assert i18n.t(job.note, "en") == "subtitles taken from the video (ita) [1/2]"
    # nessuna traccia: senza Whisper un errore chiaro, con Whisper la trascrizione
    monkeypatch.setattr(tools, "run", scripted_run({"ffprobe": '{"streams": []}'}, []))
    with pytest.raises(ConvError, match="WHISPER_URL"):
        asyncio.run(tools.video_subtitles()(job_ns(), tmp_path / "v.mp4", "srt", tmp_path))

    async def whisper(job, inp, out_ext, wd):
        out = wd / "w.srt"
        out.write_text("trascritto")
        return out

    assert asyncio.run(tools.video_subtitles(whisper)(job_ns(), tmp_path / "v.mp4", "srt", tmp_path)).read_text() == "trascritto"


def test_with_subtitles_args(tmp_path):
    subs = tmp_path / "subs.srt"
    copy = ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-movflags", "+faststart"]
    enc = ["-c:v", "libx264", "-crf", "21"]
    base = ["ffmpeg", "-i", "in.mov", "-map_metadata", "0"]
    attempts, b = tools.with_subtitles([copy, enc], base, subs, "mp4", False)
    assert b == ["ffmpeg", "-i", "in.mov", "-i", str(subs), "-map_metadata", "0"]
    assert attempts[0][-4:] == ["-map", "1:0", "-c:s", "mov_text"] and attempts[0][:2] == ["-map", "0:v:0"]
    assert attempts[1][:4] == ["-map", "0:v?", "-map", "0:a?"]
    attempts, b = tools.with_subtitles([copy, enc + ["-vf", "scale=-2:720"]], base, subs, "mp4", True)
    assert b == base and len(attempts) == 1  # la copia non puo' imprimere i sottotitoli
    assert attempts[0][-1] == f"scale=-2:720,subtitles=filename='{subs}'"
    job = job_ns()
    attempts, _ = tools.with_subtitles([enc], base, subs, "avi", False, job)
    assert attempts[0][-2:] == ["-vf", f"subtitles=filename='{subs}'"] and "AVI" in job.note
    assert tools.with_subtitles([copy], base, tmp_path / "s.ass", "mkv", False)[0][0][-1] == "ass"


def test_subtitle_options():
    g = default_graph()
    assert options.applicable(g.plan("mp4", "mp4"), "mp4")[:3] == ["start", "end", "height"]
    assert "subtitles" in options.applicable(g.plan("mov", "mkv"), "mkv")
    assert "subtitles" not in options.applicable(g.plan("mp4", "gif"), "gif")
    assert "subtitles" not in options.applicable(g.plan("mp4", "mp3"), "mp3")
    with pytest.raises(options.OptionError, match="file"):
        options.parse({"subtitles": "x.srt"}, g.plan("mov", "mp4"), "mp4")
    assert options.reencode_needed({"burn_subtitles": True})


@pytest.fixture
def video_client(tmp_path):
    seen = {}

    async def fake_ffmpeg(job, inp, out_ext, wd):
        seen["extras"] = dict(job.extras)
        seen["options"] = tools.opts_of(job, out_ext)
        seen["subs"] = Path(job.extras["subtitles"]).read_text() if job.extras.get("subtitles") else None
        out = wd / f"out.{out_ext}"
        out.write_bytes(b"video")
        return out

    g = Graph()
    g.add("mov", "mp4", fake_ffmpeg, "FFmpeg")
    g.rebuild()
    orig = options.applicable  # le opzioni dipendono dal programma: qui si fa finta che l'ultimo sia FFmpeg
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(options, "applicable",
                   lambda plan, target: orig([SimpleNamespace(fn=tools.ffmpeg, tool="FFmpeg")], target) if plan else [])
        with TestClient(create_app(Settings(work_dir=tmp_path), g)) as c:
            yield c, seen


def test_add_subtitles_api(video_client):
    c, seen = video_client
    r = c.post("/api/jobs", data={"target": "mp4", "options": '{"burn_subtitles": true}'},
               files={"file": ("a.mov", b"mov"), "subtitles": ("italiano.srt", b"1\n00:00:01,000 --> 00:00:02,000\nCiao\n")})
    assert r.status_code == 201, r.text
    assert wait(c, r.json()["id"])["state"] == "done"
    assert seen["subs"].endswith("Ciao\n") and seen["options"] == {"burn_subtitles": True}
    assert seen["extras"]["subtitles"].endswith("subs.srt")
    bad = c.post("/api/jobs", data={"target": "mp4"}, files={"file": ("a.mov", b"mov"), "subtitles": ("x.txt", b"x")})
    assert bad.status_code == 400 and "SRT" in bad.json()["detail"]
    assert c.post("/api/jobs", data={"target": "mp4", "options": '{"burn_subtitles": true}'},
                  files={"file": ("a.mov", b"mov")}).status_code == 400
    empty = c.post("/api/jobs", data={"target": "mp4"}, files={"file": ("a.mov", b"mov"), "subtitles": ("v.srt", b"")})
    assert empty.status_code == 400


def test_subtitles_only_for_video(tmp_path):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path), g)) as c:
        r = c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x"), "subtitles": ("s.srt", b"1")},
                   headers={"Accept-Language": "en"})
        assert r.status_code == 400 and r.json()["detail"] == "Subtitles can only be added to a video"


# ------------------------------------------------------------------ Graphviz

def test_graphviz_detection_and_graph(tmp_path):
    assert is_graphviz(b"digraph G { a -> b }") and is_graphviz(b"\xef\xbb\xbf  strict graph { a -- b }")
    assert is_graphviz(b"// commento\ngraph { }") and not is_graphviz(b"\xd0\xcf\x11\xe0\x00\x00 Word")
    assert not is_graphviz(b"") and not is_graphviz(b"Testo qualsiasi")
    g = default_graph()
    assert [(e.tool, e.dst) for e in g.plan("gv", "svg")] == [("Graphviz", "svg")]
    assert g.plan("gv", "png") and g.plan("gv", "pdf") and g.plan("gv", "docx") is None
    gg = Graph()
    gg.add("gv", "svg", upper, "Graphviz")
    gg.add("doc", "pdf", upper, "LibreOffice")
    gg.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path), gg)) as c:
        r = c.post("/api/jobs", data={"target": "svg"}, files={"file": ("schema.dot", b"digraph { a -> b }")})
        assert r.status_code == 201 and r.json()["filename"] == "schema.gv"
        r = c.post("/api/jobs", data={"target": "pdf"}, files={"file": ("modello.dot", b"\xd0\xcf\x11\xe0\x00\x00")})
        assert r.status_code == 201 and r.json()["filename"] == "modello.dot"


@pytest.mark.skipif(not __import__("shutil").which("dot"), reason="serve Graphviz")
def test_graphviz_real(tmp_path):
    (tmp_path / "in.gv").write_text("digraph { a -> b }")
    out = asyncio.run(tools.graphviz(job_ns(), tmp_path / "in.gv", "svg", tmp_path))
    assert b"<svg" in out.read_bytes()


# ------------------------------------------------------------------ email

def make_eml(tmp_path: Path, with_attachment=True) -> Path:
    msg = EmailMessage()
    msg["Subject"] = "Verbale della riunione"
    msg["From"] = "Anna <anna@example.org>"
    msg["To"] = "Luca <luca@example.org>"
    msg["Date"] = "Fri, 20 Nov 2026 10:00:00 +0100"
    msg.set_content("Ciao Luca,\n\nin allegato il verbale.\n\nAnna")
    msg.add_alternative('<html><body><p>Ciao <b>Luca</b>,</p><script>alert(1)</script>'
                        '<p><img src="cid:logo@x" alt="logo"> <img src="https://tracker.example/p.gif" alt="pixel">'
                        '<a href="javascript:alert(2)">link</a></p><p style="background:url(http://x/y)">fine</p>'
                        '</body></html>', subtype="html")
    msg.get_payload()[1].add_related(PNG, maintype="image", subtype="png", cid="<logo@x>")
    if with_attachment:
        msg.add_attachment(b"%PDF-1.4 verbale", maintype="application", subtype="pdf", filename="verbale.pdf")
        msg.add_attachment(b"dati", maintype="text", subtype="csv", filename="verbale.pdf")  # stesso nome
    p = tmp_path / ("mail.eml" if with_attachment else "solo.eml")
    p.write_bytes(bytes(msg))
    return p


def test_eml_to_html(tmp_path):
    pytest.importorskip("lxml")
    eml = make_eml(tmp_path)
    out = tmp_path / "out.html"
    assert subprocess.run([sys.executable, str(EMAILCONV), "html", str(eml), str(out)]).returncode == 0
    html = out.read_text()
    assert "<h1>Verbale della riunione</h1>" in html and "anna@example.org" in html and "<th>Data</th>" in html
    assert "verbale.pdf (" in html  # elenco degli allegati
    assert 'src="data:image/png;base64,' in html  # immagine cid: incorporata
    assert "tracker.example" not in html and "[immagine esterna: pixel]" in html
    assert "<script" not in html and "javascript:" not in html and "url(" not in html
    en = tmp_path / "en.html"
    subprocess.run([sys.executable, str(EMAILCONV), "html", str(eml), str(en), "en"], check=True)
    assert "<th>Date</th>" in en.read_text() and "[external image: pixel]" in en.read_text()


def test_eml_attachments_zip(tmp_path):
    eml = make_eml(tmp_path)
    out = tmp_path / "out.zip"
    subprocess.run([sys.executable, str(EMAILCONV), "zip", str(eml), str(out)], check=True)
    assert sorted(zipfile.ZipFile(out).namelist()) == ["verbale (2).pdf", "verbale.pdf"]
    none = make_eml(tmp_path, with_attachment=False)
    assert subprocess.run([sys.executable, str(EMAILCONV), "zip", str(none), str(tmp_path / "x.zip")]).returncode == 3
    bad = tmp_path / "rotta.msg"
    bad.write_bytes(b"non e' un msg")
    assert subprocess.run([sys.executable, str(EMAILCONV), "html", str(bad), str(tmp_path / "y.html")],
                          capture_output=True).returncode == 4


def test_msg_reader(monkeypatch):
    class Att:
        def __init__(self, name, data, cid="", mime="application/pdf", hidden=False):
            self.longFilename, self.shortFilename, self.data, self.cid, self.mimetype, self.hidden = \
                name, None, data, cid, mime, hidden

    class Msg:
        subject, sender, to, cc, date = "Oggetto", "a@x.org", "b@x.org", "", "2026-11-20"
        htmlBody = b'<p>Ciao <img src="cid:img1"></p>'
        body = "Ciao"
        attachments = [Att("doc.pdf", b"%PDF"), Att("img.png", PNG, cid="img1", mime="image/png", hidden=True),
                       Att("allegato.msg", object())]

        def __init__(self, path):
            pass

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "extract_msg", SimpleNamespace(Message=Msg))
    m = emailconv.read_msg("x.msg")
    assert [(p.name, p.inline) for p in m.parts] == [("doc.pdf", False), ("img.png", True)]
    html = emailconv.to_html(m)
    assert "data:image/png;base64," in html and "doc.pdf (4 B)" in html and "img.png" not in html.split("<hr>")[0]


def test_email_in_graph():
    g = default_graph()
    assert [(e.tool, e.dst) for e in g.plan("eml", "pdf")] == [("Python", "html"), ("Pandoc", "docx"),
                                                               ("LibreOffice", "pdf")]
    assert g.plan("msg", "zip")[0].tool == "Python" and g.plan("eml", "docx") and g.plan("msg", "md")


# ------------------------------------------------------------------ lavori che sopravvivono al riavvio

def make_graph(fn):
    g = Graph()
    g.add("txt", "md", fn, "Test")
    g.rebuild()
    return g


def two_graph(second):
    g = Graph()
    g.add("txt", "md", upper, "Test")
    g.add("txt", "rst", second, "Test")
    g.rebuild()
    return g


def test_jobs_survive_restart(tmp_path):
    s = Settings(work_dir=tmp_path)
    with TestClient(create_app(s, two_graph(slow))) as c:
        done = wait(c, c.post("/api/jobs", data={"target": "md", "meta": "m"}, files={"file": ("a.txt", b"ciao")}).json()["id"])
        assert done["state"] == "done"
        queued = c.post("/api/jobs", data={"target": "rst"}, files={"file": ("b.txt", b"lento")}).json()["id"]
    # stesso lavoro "lento" interrotto dallo spegnimento: al riavvio riparte con il convertitore di ora
    state = json.loads((tmp_path / "jobs" / queued / "job.json").read_text())
    assert state["state"] == "queued"
    with TestClient(create_app(s, two_graph(upper))) as c:
        again = c.get(f"/api/jobs/{done['id']}").json()
        assert again["state"] == "done" and again["meta"] == "m"
        assert c.get(f"/api/jobs/{done['id']}/download").content == b"CIAO"
        assert wait(c, queued)["state"] == "done"
        assert c.get(f"/api/jobs/{queued}/download").content == b"LENTO"


def test_interrupted_running_job_restarts(tmp_path):
    s = Settings(work_dir=tmp_path)
    with TestClient(create_app(s, make_graph(slow))) as c:
        jid = c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"ciao")}).json()["id"]
        for _ in range(50):
            if c.get(f"/api/jobs/{jid}").json()["state"] == "running":
                break
            time.sleep(0.05)
    assert (tmp_path / "jobs" / jid / "input.txt").exists()  # il file caricato resta per il riavvio
    with TestClient(create_app(s, make_graph(upper))) as c:
        assert wait(c, jid)["state"] == "done"


def test_restore_cleans_up(tmp_path):
    s = Settings(work_dir=tmp_path)
    jobs = tmp_path / "jobs"
    with TestClient(create_app(s, make_graph(upper))) as c:
        old = wait(c, c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x")}).json()["id"])["id"]
    state = json.loads((jobs / old / "job.json").read_text())
    state["finished"] = time.time() - 7 * 3600  # oltre RETAIN_HOURS
    (jobs / old / "job.json").write_text(json.dumps(state))
    evil = "f" * 32
    (jobs / evil).mkdir()
    (jobs / evil / "job.json").write_text(json.dumps({**state, "id": evil, "out_path": "../../etc/passwd",
                                                      "finished": time.time()}))
    (jobs / "spazzatura").mkdir()
    with TestClient(create_app(s, make_graph(upper))) as c:
        assert c.get(f"/api/jobs/{old}").status_code == 404 and c.get(f"/api/jobs/{evil}").status_code == 404
    assert not (jobs / old).exists() and not (jobs / evil).exists() and not (jobs / "spazzatura").exists()


def test_keep_jobs_false_wipes(tmp_path):
    s = Settings(work_dir=tmp_path, keep_jobs=False)
    with TestClient(create_app(s, make_graph(upper))) as c:
        jid = wait(c, c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x")}).json()["id"])["id"]
    with TestClient(create_app(s, make_graph(upper))) as c:
        assert c.get(f"/api/jobs/{jid}").status_code == 404
