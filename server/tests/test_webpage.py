"""Pagina web 2.4: opzioni di conversione, anteprime, file da un indirizzo, app installabile."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converter import apikeys, fetch, options, preview, tools
from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph, default_graph
from converter.tools import ffmpeg_attempts

from test_api import upper, wait

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


# ------------------------------------------------------------------ opzioni

def test_applicable_by_last_program():
    g = default_graph()
    assert options.applicable(g.plan("png", "jpg"), "jpg") == ["quality", "max_size", "strip"]
    assert options.applicable(g.plan("jpg", "png"), "png") == ["max_size", "strip"]
    assert options.applicable(g.plan("mov", "mp4"), "mp4") == ["start", "end", "height", "video_quality",
                                                             "audio_bitrate", "strip"]
    assert options.applicable(g.plan("mp4", "gif"), "gif") == ["start", "end", "height", "strip"]
    assert options.applicable(g.plan("wav", "mp3"), "mp3") == ["start", "end", "audio_bitrate", "mono", "strip"]
    assert options.applicable(g.plan("wav", "flac"), "flac") == ["start", "end", "mono", "strip"]
    assert options.applicable(g.plan("pdf", "png"), "png") == ["dpi", "pages"]
    assert options.applicable(g.plan("docx", "pdf"), "pdf") == []


def test_parse_options():
    g = default_graph()
    plan = g.plan("mp4", "mp3")
    assert options.parse('{"start": "1:30", "end": "2:00.5", "audio_bitrate": "128", "mono": true}', plan, "mp3") == \
        {"start": 90.0, "end": 120.5, "audio_bitrate": "128", "mono": True}
    assert options.parse({"start": "0", "mono": False, "end": ""}, plan, "mp3") == {}
    for bad, msg in [('{"end": "0:10", "start": "0:20"}', "dopo"), ('{"audio_bitrate": "100"}', "non valido"),
                     ('{"quality": 80}', "non disponibile"), ('{"pippo": 1}', "sconosciuta"), ("[1]", "JSON"),
                     ("{", "JSON"), ('{"start": "1:2:3:4"}', "non valido")]:
        with pytest.raises(options.OptionError, match=msg):
            options.parse(bad, plan, "mp3")
    img = g.plan("png", "jpg")
    assert options.parse({"quality": "75", "max_size": 1280, "strip": "true"}, img, "jpg") == \
        {"quality": 75, "max_size": 1280, "strip": True}
    for bad in ({"quality": 0}, {"quality": 101}, {"max_size": "abc"}, {"quality": 7.5}):
        with pytest.raises(options.OptionError):
            options.parse(bad, img, "jpg")
    pdf = g.plan("pdf", "jpg")
    assert options.parse({"pages": "3-5", "dpi": "300"}, pdf, "jpg") == {"pages": [3, 5], "dpi": "300"}
    assert options.parse({"pages": "2"}, pdf, "jpg") == {"pages": [2, 2]}
    assert options.parse({"pages": "4-"}, pdf, "jpg") == {"pages": [4, 0]}
    for bad in ("0", "5-3", "a", "1,3"):
        with pytest.raises(options.OptionError):
            options.parse({"pages": bad}, pdf, "jpg")


def test_ffmpeg_args_with_options():
    # nessuna opzione: prima la copia senza ricodifica, come prima
    assert ffmpeg_attempts("mp4", "h264", "aac", {})[0][-4:] == ["-c", "copy", "-movflags", "+faststart"]
    # taglio o risoluzione: solo ricodifica
    a = ffmpeg_attempts("mp4", "h264", "aac", {"height": "720", "video_quality": "low", "audio_bitrate": "96"})
    assert len(a) == 1 and a[0][a[0].index("-vf") + 1] == "scale=-2:'min(720,ih)'"
    assert a[0][a[0].index("-crf") + 1] == "28" and a[0][-2:] == ["-b:a", "96k"]
    assert len(ffmpeg_attempts("mp4", "h264", "aac", {"start": 5.0})) == 1
    webm = ffmpeg_attempts("webm", "", "", {"video_quality": "high"})[0]
    assert webm[webm.index("-crf") + 1] == "26"
    mp3 = ffmpeg_attempts("mp3", "", "", {"audio_bitrate": "128", "mono": True})[0]
    assert "-q:a" not in mp3 and mp3[-4:] == ["-b:a", "128k", "-ac", "1"]
    gif = ffmpeg_attempts("gif", "", "", {"height": "360", "end": 10.0})[0]
    assert "-t" not in gif and "scale=-2:'min(360,ih)'" in gif[gif.index("-filter_complex") + 1]
    assert ffmpeg_attempts("gif", "", "", {})[0][:2] == ["-t", "60"]
    assert options.ffmpeg_input_args({"start": 90.0, "end": 120.5}) == ["-ss", "90", "-t", "30.5"]
    assert options.magick_args({"max_size": 800, "strip": True}, "jpg", True) == ["-resize", "800x800>", "-strip"]


def test_options_reach_the_converter(tmp_path, monkeypatch):
    seen = {}

    async def fake_magick(job, inp, out_ext, wd):
        seen.update(tools.opts_of(job, out_ext))
        out = wd / f"out.{out_ext}"
        out.write_bytes(PNG)
        return out

    monkeypatch.setattr(tools, "imagemagick", fake_magick)
    g = Graph()
    g.add("png", "jpg", fake_magick, "ImageMagick")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path), g)) as c:
        assert [o["name"] for o in c.get("/api/options/png/jpg").json()["options"]] == ["quality", "max_size", "strip"]
        assert c.get("/api/options/png/xyz").status_code == 404
        r = c.post("/api/jobs", data={"target": "jpg", "options": '{"quality": 70, "strip": true}'},
                   files={"file": ("a.png", PNG)})
        assert r.status_code == 201, r.text
        st = wait(c, r.json()["id"])
        assert st["state"] == "done" and st["options"] == {"quality": 70, "strip": True}
        assert seen == {"quality": 70, "strip": True}
        bad = c.post("/api/jobs", data={"target": "jpg", "options": '{"quality": 700}'}, files={"file": ("a.png", PNG)},
                     headers={"Accept-Language": "en"})
        assert bad.status_code == 400 and bad.json()["detail"] == "invalid value for 'Quality (1-100)': 700"


# ------------------------------------------------------------------ anteprime

def test_preview_kinds(tmp_path):
    g = default_graph()
    f = tmp_path / "x"
    f.write_bytes(b"x")
    cases = {"a.jpg": "image", "a.heic": "image", "a.pdf": "image", "a.svg": "image", "a.txt": "text",
             "a.html": "text", "a.json": "text", "a.mp3": "audio", "a.wma": "audio", "a.mp4": "video",
             "a.mkv": "video", "a.tar.gz": "text", "a.docx": "image", "a.xlsx": "image", "a.woff2": "",
             "a.mobi": ""}
    for name, kind in cases.items():
        assert preview.kind(f, name, g) == kind, name
    import zipfile
    z = tmp_path / "pagine.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("pagina-1.png", PNG)
    assert preview.kind(z, "pagine.zip", g) == "image"


@pytest.fixture
def client(tmp_path):
    async def png(job, inp, out_ext, wd):
        out = wd / "out.png"
        out.write_bytes(PNG)
        return out

    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.add("txt", "png", png, "Png")
    g.add("txt", "mobi", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, url_allow_private=True), g)) as c:
        yield c


def test_preview_api(client):
    job = client.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"ciao <script>")}).json()
    st = wait(client, job["id"])
    assert st["preview"] == "text"
    r = client.get(f"/api/jobs/{job['id']}/preview")
    assert r.status_code == 200 and r.text == "CIAO <SCRIPT>" and r.headers["content-type"].startswith("text/plain")
    assert "sandbox" in r.headers["content-security-policy"]
    img = client.post("/api/jobs", data={"target": "png"}, files={"file": ("a.txt", b"x")}).json()
    assert wait(client, img["id"])["preview"] == "image"
    r = client.get(f"/api/jobs/{img['id']}/preview")
    assert r.content == PNG and r.headers["content-type"] == "image/png"
    font = client.post("/api/jobs", data={"target": "mobi"}, files={"file": ("a.txt", b"x")}).json()
    assert "preview" not in wait(client, font["id"])
    assert client.get(f"/api/jobs/{font['id']}/preview").status_code == 404


# ------------------------------------------------------------------ file da un indirizzo

class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/file.txt")
            self.end_headers()
        elif self.path == "/file.txt":
            body = b"testo dal sito"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/download.php":
            body = b"altro testo"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/cd":
            body = b"con nome"
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="relazione finale.txt"')
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 5000)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def site():
    srv = HTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_fetch_checks(tmp_path, site):
    for bad in ("", "ftp://x/y", "file:///etc/passwd", "http://user:pw@example.com/a", "javascript:alert(1)"):
        with pytest.raises(fetch.FetchError):
            fetch.check_url(bad)
    for ip in ("127.0.0.1", "10.1.2.3", "192.168.1.10", "100.64.1.1", "169.254.169.254", "::1", "fd00::1",
               "::ffff:192.168.1.1", "0.0.0.0"):
        with pytest.raises(fetch.FetchError):
            fetch._check_ip(ip, False)
    fetch._check_ip("8.8.8.8", False)
    fetch._check_ip("192.168.1.10", True)
    with pytest.raises(fetch.FetchError, match="rete locale"):
        fetch.download(site + "/file.txt", tmp_path / "f", 1000, allow_private=False)
    assert fetch.download(site + "/go", tmp_path / "f", 1000, True) == ("file.txt", "txt", 14)
    assert fetch.download(site + "/download.php", tmp_path / "f", 1000, True)[:2] == ("download.php", "txt")
    assert fetch.download(site + "/cd", tmp_path / "f", 1000, True)[0] == "relazione finale.txt"
    with pytest.raises(fetch.FetchError, match="grande"):
        fetch.download(site + "/big", tmp_path / "f", 1000, True)
    with pytest.raises(fetch.FetchError, match="404"):
        fetch.download(site + "/nope", tmp_path / "f", 1000, True)


def test_fetch_then_convert(client, site):
    r = client.post("/api/fetch", data={"url": site + "/download.php"})
    assert r.status_code == 201, r.text
    st = r.json()
    assert st["filename"] == "download.txt" and st["ext"] == "txt" and "md" in st["targets"] and st["size"] == 11
    job = client.post("/api/jobs", data={"target": "md", "staged": st["staged"]})
    assert job.status_code == 201, job.text
    done = wait(client, job.json()["id"])
    assert done["out_name"] == "download.md"
    assert client.get(f"/api/jobs/{job.json()['id']}/download").content == b"ALTRO TESTO"
    # il file scaricato si usa una volta sola
    assert client.post("/api/jobs", data={"target": "md", "staged": st["staged"]}).status_code == 404
    assert client.post("/api/jobs", data={"target": "md"}).status_code == 400


def test_fetch_private_blocked_by_default(tmp_path, site):
    with TestClient(create_app(Settings(work_dir=tmp_path), Graph())) as c:
        r = c.post("/api/fetch", data={"url": site + "/file.txt"}, headers={"Accept-Language": "en"})
        assert r.status_code == 400 and "Local network" in r.json()["detail"]
    with TestClient(create_app(Settings(work_dir=tmp_path, url_import=False), Graph())) as c:
        assert c.post("/api/fetch", data={"url": site + "/file.txt"}).status_code == 404


# ------------------------------------------------------------------ app installabile e permessi

def test_pwa_files(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json")
    data = json.loads(m.text)
    assert data["share_target"]["action"] == "share" and data["start_url"] == "./"
    for icon in data["icons"]:
        assert client.get("/" + icon["src"]).status_code == 200, icon["src"]
    assert "receiveShare" in client.get("/sw.js").text
    assert client.get("/static/apple-touch-icon.png").status_code == 200
    assert client.get("/static/admin.html").status_code == 404
    assert client.get("/static/..%2Fapp.py").status_code == 404
    r = client.post("/share", follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/").text
    assert 'rel="manifest"' in page and "takeShared" in page


def test_permissions_for_new_paths():
    assert apikeys.permission_for("GET", "/api/options/png/jpg") == "formats"
    assert apikeys.permission_for("POST", "/api/fetch") == "convert"
    assert apikeys.permission_for("GET", "/api/jobs/abc/preview") == "jobs"
    assert apikeys.permission_for("GET", "/manifest.webmanifest") is None


def test_same_format_only_with_its_own_plan():
    g = default_graph()
    assert g.plan("mp4", "mp4")[0].fn is tools.ffmpeg and g.plan("jpeg", "jpg")[0].fn is tools.imagemagick
    assert g.plan("pdf", "pdf") is None and g.plan("docx", "docx") is None
    p = g.payload()
    assert "mp4" in p["same"] and "jpeg" in p["same"] and "pdf" not in p["same"]
    assert "mp4" not in p["inputs"]["mp4"]  # i menu di Nextcloud restano come prima
    assert options.applicable(g.plan("jpg", "jpg"), "jpg") == ["quality", "max_size", "strip"]
    g.disable([("mp3", "mp3")])
    assert g.plan("mp3", "mp3") is None and "mp3" not in g.payload()["same"]
