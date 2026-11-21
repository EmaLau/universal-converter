"""Prova l'API con convertitori finti: non servono LibreOffice, FFmpeg e gli altri programmi."""
import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph
from converter.runner import ConvError


async def upper(job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    out.write_text(inp.read_text().upper())
    return out


async def fail(job, inp, out_ext, wd):
    raise ConvError("rotto apposta")


async def slow(job, inp, out_ext, wd):
    await asyncio.sleep(30)


@pytest.fixture
def client(tmp_path):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.add("md", "html", upper, "Upper")
    g.add("txt", "rst", fail, "Fail")
    g.add("txt", "tex", slow, "Slow")
    g.rebuild()
    settings = Settings(work_dir=tmp_path, max_upload_bytes=1024, max_queue=5)
    with TestClient(create_app(settings, g)) as c:
        yield c


def wait(client, job_id, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/jobs/{job_id}").json()
        if st["state"] in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("lavoro non finito")


def upload(client, name, data, target):
    return client.post("/api/jobs", data={"target": target}, files={"file": (name, data)})


def test_index_and_health(client):
    assert "Convertitore" in client.get("/").text
    assert client.get("/healthz").json()["ok"] is True


def test_formats(client):
    f = client.get("/api/formats").json()
    assert set(f["inputs"]["txt"]) == {"md", "html", "rst", "tex"}
    assert f["retain_hours"] == 6.0


def test_two_step_conversion_and_download(client, tmp_path):
    r = upload(client, "../Appunti finali.txt", b"ciao", "html")
    assert r.status_code == 201
    st = wait(client, r.json()["id"])
    assert st["state"] == "done" and st["out_name"] == "Appunti finali.html"
    d = client.get(f"/api/jobs/{st['id']}/download")
    assert d.content == b"CIAO"
    assert "Appunti%20finali.html" in d.headers["content-disposition"]
    assert client.delete(f"/api/jobs/{st['id']}").json() == {"ok": True}
    assert client.get(f"/api/jobs/{st['id']}").status_code == 404
    assert not any((tmp_path / "jobs").iterdir())


def test_errors(client):
    assert upload(client, "a.pdf", b"x", "md").status_code == 400
    assert upload(client, "a.txt", b"", "md").status_code == 400
    assert upload(client, "a.txt", b"x" * 2048, "md").status_code == 413
    st = wait(client, upload(client, "a.txt", b"x", "rst").json()["id"])
    assert st["state"] == "error" and "rotto apposta" in st["error"]
    r = upload(client, "a.txt", b"x", "md")
    assert client.get(f"/api/jobs/{r.json()['id']}/download").status_code in (200, 409)


def test_delete_running_job_and_queue_limit(client):
    ids = [upload(client, "a.txt", b"x", "tex").json()["id"] for _ in range(5)]
    assert upload(client, "a.txt", b"x", "tex").status_code == 503
    for i in ids:
        assert client.delete(f"/api/jobs/{i}").status_code == 200
    assert client.get("/healthz").json()["jobs"] == 0


def test_cleanup_removes_old_jobs(client):
    st = wait(client, upload(client, "a.txt", b"x", "md").json()["id"])
    manager = client.app.state.manager
    assert manager.cleanup(now=time.time() + 7 * 3600) == 1
    assert client.get(f"/api/jobs/{st['id']}").status_code == 404


def test_health_lists_programs(client):
    h = client.get("/healthz").json()
    assert set(h["programs"]) >= {"LibreOffice", "FFmpeg", "Pandoc", "qpdf"}
    assert all(isinstance(v, bool) for v in h["programs"].values())


def test_zip_of_results(client):
    import io
    import zipfile
    a = wait(client, upload(client, "nota.txt", b"uno", "md").json()["id"])
    b = wait(client, upload(client, "altra/nota.txt", b"due", "md").json()["id"])  # stesso nome di risultato
    r = client.post("/api/jobs/zip", data={"ids": f"{a['id']},{b['id']},nope", "lang": "en"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "converted.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["nota (2).md", "nota.md"]
    assert {z.read(n) for n in z.namelist()} == {b"UNO", b"DUE"}
    assert client.post("/api/jobs/zip", data={"ids": "nope"}).status_code == 404
    r = client.post("/api/jobs/zip", data={"ids": a["id"]}, headers={"Accept-Language": "it"})
    assert "convertiti.zip" in r.headers["content-disposition"]


def test_plico_url(tmp_path):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, plico_url=":30128"), g)) as c:
        assert c.get("/api/formats").json()["plico_url"] == ":30128"
    assert Settings.from_env({"PLICO_URL": " http://nas:30128 "}).plico_url == "http://nas:30128"


def test_fuzz_cases_are_built():
    """I casi di fuzz.py si generano senza programmi esterni (lo ZIP da 1 GB escluso: lento)."""
    import fuzz
    assert fuzz.png_header_bomb().startswith(b"\x89PNG")
    assert b"&l9;" in fuzz.svg_laughs()
    assert b"/Kids [2 0 R" in fuzz.pdf_page_loop()
    assert len(fuzz.zip_bomb(2)) < 64 * 1024
