"""Webhook, limiti per chiave API, metriche Prometheus e messaggi d'errore senza percorsi interni (2.4)."""
import asyncio
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converter import webhooks
from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph
from converter.jobs import Job, JobManager
from converter.runner import ConvError

from test_api import upper, wait
from test_apikeys import PW, XRW, login

SECRET = "segreto-dei-webhook"


async def slow(job, inp: Path, out_ext: str, wd: Path) -> Path:
    await asyncio.sleep(1.5)
    return await upper(job, inp, out_ext, wd)


async def broken(job, inp: Path, out_ext: str, wd: Path) -> Path:
    raise ConvError(f"magick ha restituito 1: improper image header `{inp}' @ error/png.c")


def make(tmp_path, **kw):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.add("txt", "html", slow, "Slow")
    g.add("txt", "rst", broken, "Broken")
    g.rebuild()
    return TestClient(create_app(Settings(work_dir=tmp_path, admin_password=PW, **kw), g, pdf_tools={}))


@pytest.fixture
def receiver():
    """Piccolo server HTTP locale che registra i webhook ricevuti."""
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.append((dict(self.headers), body))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/hook", got
    srv.shutdown()


def until(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def key_with(c, **limits):
    login(c)
    r = c.post("/admin/api/keys", json={"name": "script", "perms": ["formats", "convert", "jobs"], **limits},
               headers=XRW)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------------------ webhook

def test_webhook_delivered_and_signed(tmp_path, receiver):
    url, got = receiver
    with make(tmp_path, webhook_secret=SECRET) as c:
        r = c.post("/api/jobs", data={"target": "md", "callback_url": url}, files={"file": ("a.txt", b"ciao")})
        assert r.status_code == 201 and r.json()["webhook"] == "pending"
        st = wait(c, r.json()["id"])
        assert st["state"] == "done"
        assert until(lambda: got)
        headers, body = got[0]
        assert headers["X-Converter-Event"] == "job.done"
        assert headers["X-Converter-Signature"] == "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert json.loads(body)["out_name"] == "a.md"
        assert until(lambda: c.get(f"/api/jobs/{st['id']}").json()["webhook"] == "ok")
        assert 'uconv_webhooks_total{result="ok"} 1' in c.get("/metrics").text


def test_webhook_error_in_job_language(tmp_path, receiver):
    url, got = receiver
    with make(tmp_path) as c:
        r = c.post("/api/jobs", data={"target": "rst", "callback_url": url}, files={"file": ("a.txt", b"x")},
                   headers={"Accept-Language": "en"})
        wait(c, r.json()["id"])
        assert until(lambda: got)
        headers, body = got[0]
        assert headers["X-Converter-Event"] == "job.error" and "X-Converter-Signature" not in headers
        assert json.loads(body)["error"].startswith("magick returned 1")


def test_webhook_url_checked(tmp_path):
    with make(tmp_path, webhook_hosts=frozenset({"n8n.lan"})) as c:
        def post(cb):
            return c.post("/api/jobs", data={"target": "md", "callback_url": cb}, files={"file": ("a.txt", b"x")})
        assert post("ftp://n8n.lan/x").status_code == 400
        assert "host non ammesso" in post("http://evil.example/x").json()["detail"]
        assert post("http://n8n.lan/hook").status_code == 201


def test_webhook_retries_then_reports_error():
    async def run():
        return await webhooks.deliver("http://127.0.0.1:9/nothing", {"state": "done"}, delays=(0, 0))
    assert asyncio.run(run()) != "ok"


# ------------------------------------------------------------------------------------- limiti delle chiavi

def test_limit_concurrent_jobs(tmp_path):
    with make(tmp_path) as c:
        k = key_with(c, max_jobs=1)
        h = {"apikey": k["key"]}
        first = c.post("/api/jobs", data={"target": "html"}, files={"file": ("a.txt", b"x")}, headers=h)
        assert first.status_code == 201
        second = c.post("/api/jobs", data={"target": "md"}, files={"file": ("b.txt", b"x")}, headers=h)
        assert second.status_code == 429 and "1 lavori in corso" in second.json()["detail"]
        # la pagina web (sessione, senza chiave) non e' limitata
        assert c.post("/api/jobs", data={"target": "md"}, files={"file": ("c.txt", b"x")}).status_code == 201
        wait(c, first.json()["id"])
        assert c.post("/api/jobs", data={"target": "md"}, files={"file": ("b.txt", b"x")}, headers=h).status_code == 201
        assert 'uconv_rejected_total{reason="jobs"} 1' in c.get("/metrics").text


def test_limit_daily_volume(tmp_path):
    with make(tmp_path) as c:
        k = key_with(c, max_daily_mb=1)
        h = {"apikey": k["key"]}
        ok = c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"x" * 700_000)}, headers=h)
        assert ok.status_code == 201
        over = c.post("/api/jobs", data={"target": "md"}, files={"file": ("b.txt", b"x" * 500_000)}, headers=h)
        assert over.status_code == 429 and "giornaliero" in over.json()["detail"]
        keys = c.get("/admin/api/keys").json()["keys"]
        assert keys[0]["max_daily_mb"] == 1 and keys[0]["used_today_mb"] == 0.7


def test_limits_editable(tmp_path):
    with make(tmp_path) as c:
        k = key_with(c)
        assert k["max_jobs"] is None and k["max_daily_mb"] is None
        r = c.put(f"/admin/api/keys/{k['id']}", json={"max_jobs": 3, "max_daily_mb": 500}, headers=XRW).json()
        assert (r["max_jobs"], r["max_daily_mb"], r["perms"]) == (3, 500, ["formats", "convert", "jobs"])
        r = c.put(f"/admin/api/keys/{k['id']}", json={"max_jobs": None}, headers=XRW).json()
        assert (r["max_jobs"], r["max_daily_mb"]) == (None, 500)
        assert c.put(f"/admin/api/keys/{k['id']}", json={"max_jobs": "tanti"}, headers=XRW).status_code == 400


# ---------------------------------------------------------------------------------------------- metriche

def test_metrics(tmp_path):
    with make(tmp_path) as c:
        wait(c, c.post("/api/jobs", data={"target": "md"}, files={"file": ("a.txt", b"ciao")}).json()["id"])
        wait(c, c.post("/api/jobs", data={"target": "rst"}, files={"file": ("a.txt", b"x")}).json()["id"])
        m = c.get("/metrics")
        assert m.headers["content-type"].startswith("text/plain")
        assert 'uconv_jobs_finished_total{kind="convert",state="done"} 1' in m.text
        assert 'uconv_jobs_finished_total{kind="convert",state="error"} 1' in m.text
        assert "uconv_upload_bytes_total 5" in m.text
        assert "# TYPE uconv_job_duration_seconds_total counter" in m.text
    with make(tmp_path / "off", metrics=False) as c:
        assert c.get("/metrics").status_code == 404


def test_settings_from_env():
    s = Settings.from_env({"WEBHOOK_SECRET": "x", "WEBHOOK_HOSTS": "N8N.lan, paperless ", "METRICS": "false"})
    assert s.webhook_secret == "x" and s.webhook_hosts == {"n8n.lan", "paperless"} and s.metrics is False


# ------------------------------------------------------------------------------ errori senza percorsi interni

def test_error_without_internal_paths(tmp_path):
    with make(tmp_path) as c:
        st = wait(c, c.post("/api/jobs", data={"target": "rst"}, files={"file": ("foto.txt", b"x")}).json()["id"])
        assert "/jobs/" not in st["error"] and str(tmp_path) not in st["error"]
        assert "`input.txt'" in st["error"]


def test_clean_keeps_other_text():
    job = Job(id="a" * 32, dir=Path("/work/jobs/" + "a" * 32), filename="x", src_ext="png", target="jpg")
    msg = f"magick: bad `/work/jobs/{'a' * 32}/step2/input.png' @ png.c"
    assert JobManager._clean(job, msg) == "magick: bad `input.png' @ png.c"
