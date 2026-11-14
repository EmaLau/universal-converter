"""Strumenti PDF: intervalli di pagine, opzioni, API e (se qpdf/Ghostscript/Poppler sono installati) prove vere."""
import asyncio
import shutil
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from converter import pdftools
from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph
from converter.pdftools import OptionError, PdfTool, complement, parse_ranges, qpdf_ranges
from converter.runner import ConvError

from test_api import upper, wait


def make_pdf(pages: int) -> bytes:
    """PDF minimo valido con una scritta per pagina, senza programmi esterni."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", ""]
    kids = []
    font = 3 + 2 * pages
    for n in range(pages):
        page, content = 3 + 2 * n, 4 + 2 * n
        kids.append(f"{page} 0 R")
        stream = f"BT /F1 24 Tf 72 720 Td (Pagina {n + 1}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {pages} >>"
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# ------------------------------------------------------------------------------------- intervalli di pagine
def test_parse_ranges():
    assert parse_ranges("1-3, 5, 8-") == [(1, 3), (5, 5), (8, None)]
    assert parse_ranges("1 - 3 ; 5") == [(1, 3), (5, 5)]
    assert parse_ranges("-2") == [(1, 2)]
    assert parse_ranges("8-", total=10) == [(8, 10)]
    for bad in ("", "a", "3-1", "0", "1--2", "1,2-x"):
        with pytest.raises(OptionError):
            parse_ranges(bad)
    with pytest.raises(OptionError, match="10 pagine"):
        parse_ranges("9-12", total=10)


def test_qpdf_ranges_and_complement():
    assert qpdf_ranges([(1, 3), (5, 5), (8, None)]) == "1-3,5,8-z"
    assert complement([(2, 3), (6, None)], 7) == [(1, 1), (4, 5)]
    assert complement([(1, None)], 4) == []


def test_option_parsing():
    tools = {t.name: t for t in pdftools.TOOLS}
    assert tools["rotate"].parse({"angle": "180"}) == {"angle": 180, "pages": ""}
    assert tools["rotate"].parse({}) == {"angle": 90, "pages": ""}
    assert tools["compress"].parse({}) == {"level": "medium"}
    assert tools["ocr"].parse({"lang": "ITA", "force": "true"}) == {"lang": "ita", "force": True}
    for name, form in (("rotate", {"angle": "45"}), ("compress", {"level": "max"}), ("extract", {}),
                       ("ocr", {"lang": "ita; rm -rf"}), ("split", {"pages": "x"})):
        with pytest.raises(OptionError):
            tools[name].parse(form)


# ------------------------------------------------------------------------------------------------------ API
async def fake_merge(job, inputs, opts, wd):
    out = wd / "out.pdf"
    out.write_bytes(b"".join(p.read_bytes() for p in inputs))
    return out, "unito.pdf"


async def fake_fail(job, inputs, opts, wd):
    raise ConvError("rotto apposta")


async def fake_pages(job, inputs, opts, wd):
    parse_ranges(opts["pages"], total=3)


FAKE = {"merge": PdfTool("merge", "Unisci PDF", "", "Unisci", fake_merge, min_files=2, max_files=3),
        "rotate": PdfTool("rotate", "Ruota PDF", "", "Ruota", fake_fail, options=pdftools.TOOLS[4].options),
        "extract": PdfTool("extract", "Estrai pagine", "", "Estrai", fake_pages, options=pdftools.TOOLS[2].options)}


@pytest.fixture
def client(tmp_path):
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, max_upload_bytes=1024), g, FAKE)) as c:
        yield c


def files(*items):
    return [("files", (name, data)) for name, data in items]


def test_pdf_list(client):
    r = client.get("/api/pdf").json()
    assert [t["name"] for t in r["tools"]] == ["merge", "rotate", "extract"]
    assert r["tools"][1]["options"][0]["name"] == "angle"


def test_merge_job(client, tmp_path):
    r = client.post("/api/pdf/merge", files=files(("a.pdf", b"A"), ("b.pdf", b"B")))
    assert r.status_code == 201, r.text
    assert r.json()["tool"] == "merge" and r.json()["files"] == 2
    st = wait(client, r.json()["id"])
    assert st["state"] == "done" and st["out_name"] == "unito.pdf"
    assert client.get(f"/api/jobs/{st['id']}/download").content == b"AB"
    assert not list((tmp_path / "jobs" / st["id"]).glob("input-*"))  # i file caricati sono gia' cancellati


def test_pdf_errors(client):
    assert client.post("/api/pdf/nope", files=files(("a.pdf", b"A"))).status_code == 404
    assert client.post("/api/pdf/merge", files=files(("a.pdf", b"A"))).status_code == 400
    assert client.post("/api/pdf/merge", files=files(*[(f"{i}.pdf", b"A") for i in range(4)])).status_code == 400
    assert client.post("/api/pdf/merge", files=files(("a.pdf", b"A"), ("b.txt", b"B"))).status_code == 400
    assert client.post("/api/pdf/merge", files=files(("a.pdf", b"A"), ("b.pdf", b""))).status_code == 400
    assert client.post("/api/pdf/merge", files=files(("a.pdf", b"A"), ("b.pdf", b"x" * 2048))).status_code == 413
    r = client.post("/api/pdf/rotate", files=files(("a.pdf", b"A")), data={"angle": "45"})
    assert r.status_code == 400 and "Rotazione" in r.json()["detail"]
    st = wait(client, client.post("/api/pdf/rotate", files=files(("a.pdf", b"A"))).json()["id"])
    assert st["state"] == "error" and "rotto apposta" in st["error"]
    assert client.get("/healthz").json()["jobs"] == 1  # la cartella dei lavori rifiutati e' gia' sparita
    st = wait(client, client.post("/api/pdf/extract", files=files(("a.pdf", b"A")), data={"pages": "9-12"}).json()["id"])
    assert st["state"] == "error" and st["error"] == "il PDF ha 3 pagine: '9-12' va oltre"


def test_pdf_needs_key_permission(tmp_path):
    from test_apikeys import PW, XRW
    g = Graph()
    g.add("txt", "md", upper, "Upper")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, admin_password=PW, require_key=True), g, FAKE)) as c:
        c.post("/admin/api/login", json={"password": PW}, headers=XRW)
        key = c.post("/admin/api/keys", json={"name": "solo formati", "perms": ["formats"]}, headers=XRW).json()["key"]
        c.cookies.clear()
        assert c.get("/api/pdf").status_code == 401
        assert c.get("/api/pdf", headers={"apikey": key}).status_code == 200
        r = c.post("/api/pdf/merge", files=files(("a.pdf", b"A"), ("b.pdf", b"B")), headers={"apikey": key})
        assert r.status_code == 403


# ------------------------------------------------------------------------------- prove con i programmi veri
needs = lambda *names: pytest.mark.skipif(not all(shutil.which(n) for n in names),
                                          reason=f"servono {', '.join(names)}")


def job_for(tmp_path, name="prova.pdf"):
    return SimpleNamespace(filename=name, progress=None, note="", step="")


def run_tool(tool, tmp_path, inputs, form=None):
    t = {x.name: x for x in pdftools.TOOLS}[tool]
    wd = tmp_path / f"wd-{tool}-{time.monotonic_ns()}"
    wd.mkdir()
    job = job_for(tmp_path)
    out, name = asyncio.run(t.fn(job, inputs, t.parse(form or {}), wd))
    return job, out, name


def pages_of(path: Path) -> int:
    return asyncio.run(pdftools.pdf_page_count(path))


@pytest.fixture
def pdfs(tmp_path):
    out = []
    for n in (3, 2):
        p = tmp_path / f"in{n}.pdf"
        p.write_bytes(make_pdf(n))
        out.append(p)
    return out


@needs("qpdf", "pdfinfo")
def test_real_qpdf_tools(tmp_path, pdfs):
    _, out, name = run_tool("merge", tmp_path, pdfs)
    assert pages_of(out) == 5 and name == "prova-unito.pdf"
    _, out, name = run_tool("split", tmp_path, pdfs[:1])
    assert name == "prova-diviso.zip" and len(zipfile.ZipFile(out).namelist()) == 3
    _, out, _ = run_tool("split", tmp_path, pdfs[:1], {"pages": "1-2, 3"})
    assert sorted(zipfile.ZipFile(out).namelist()) == ["prova-1-2.pdf", "prova-3.pdf"]
    _, out, _ = run_tool("extract", tmp_path, pdfs[:1], {"pages": "2-"})
    assert pages_of(out) == 2
    _, out, _ = run_tool("remove", tmp_path, pdfs[:1], {"pages": "1"})
    assert pages_of(out) == 2
    _, out, _ = run_tool("rotate", tmp_path, pdfs[:1], {"angle": "90", "pages": "1"})
    assert pages_of(out) == 3
    with pytest.raises(OptionError):
        run_tool("extract", tmp_path, pdfs[:1], {"pages": "4"})
    with pytest.raises(ConvError):
        run_tool("remove", tmp_path, pdfs[:1], {"pages": "1-"})


@needs("gs")
def test_real_compress(tmp_path, pdfs):
    job, out, name = run_tool("compress", tmp_path, pdfs[:1], {"level": "high"})
    assert name == "prova-compresso.pdf" and out.stat().st_size > 0 and job.note


@needs("ocrmypdf", "tesseract")
def test_real_ocr(tmp_path, pdfs):
    _, out, name = run_tool("ocr", tmp_path, pdfs[:1], {"lang": "eng"})
    assert name == "prova-ocr.pdf" and out.read_bytes().startswith(b"%PDF")
