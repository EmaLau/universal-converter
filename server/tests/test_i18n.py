"""Lingua delle risposte: italiano di base, inglese con Accept-Language; pagine con il selettore IT / EN."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from converter import i18n
from converter.app import create_app
from converter.config import Settings
from converter.graph import Graph
from converter.runner import ConvError

STATIC = Path(__file__).resolve().parents[1] / "converter" / "static"


async def fail(job, inp, out_ext, wd):
    raise ConvError("LibreOffice non ha prodotto il file (formato non riconosciuto o file danneggiato)")


@pytest.fixture
def client(tmp_path):
    g = Graph()
    g.add("txt", "rst", fail, "Fail")
    g.rebuild()
    with TestClient(create_app(Settings(work_dir=tmp_path, max_upload_bytes=1024), g, pdf_tools={})) as c:
        yield c


def test_pick():
    assert i18n.pick(None) == "it"
    assert i18n.pick("") == "it"
    assert i18n.pick("*") == "it"
    assert i18n.pick("it-IT,it;q=0.9,en;q=0.8") == "it"
    assert i18n.pick("en-US,en;q=0.9") == "en"
    assert i18n.pick("de-DE") == "en"


def test_translate_messages():
    assert i18n.t("File vuoto", "it") == "File vuoto"
    assert i18n.t("File vuoto", "en") == "Empty file"
    assert i18n.t("Non so convertire .xyz in .pdf", "en") == "Cannot convert .xyz to .pdf"
    assert i18n.t("Unisci PDF: servono da 2 a 50 PDF", "en") == "Merge PDF: 2 to 50 PDFs are needed"
    assert i18n.t("valore non valido per 'Rotazione': 45", "en") == "invalid value for 'Rotation': 45"
    assert i18n.t("dimensione ridotta del 40%", "en") == "size reduced by 40%"
    assert i18n.t("ffmpeg ha restituito 1: Invalid data found", "en") == "ffmpeg returned 1: Invalid data found"
    assert i18n.t("Comprimi PDF", "en") == "Compress PDF"
    assert i18n.t("qualcosa di nuovo", "en") == "qualcosa di nuovo"  # non in tabella: resta com'e'


def test_every_pattern_compiles_and_has_matching_groups():
    for it, en in i18n._EN:
        rx = re.compile(f"^{it}$")
        refs = {int(n) for n in re.findall(r"\\(\d)", en)}
        assert refs <= set(range(1, rx.groups + 1)), it


def test_api_errors_follow_accept_language(client):
    r = client.post("/api/jobs", files={"file": ("a.xyz", b"x")}, data={"target": "pdf"})
    assert r.status_code == 400 and r.json()["detail"] == "Non so convertire .xyz in .pdf"
    r = client.post("/api/jobs", files={"file": ("a.xyz", b"x")}, data={"target": "pdf"},
                    headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.json()["detail"] == "Cannot convert .xyz to .pdf"
    assert r.headers["content-language"] == "en"
    r = client.get("/api/jobs/nope", headers={"Accept-Language": "en"})
    assert r.status_code == 404 and r.json()["detail"].startswith("Job not found")


def test_job_error_translated(client):
    import time
    job = client.post("/api/jobs", files={"file": ("a.txt", b"ciao")}, data={"target": "rst"}).json()
    for _ in range(50):
        it = client.get(f"/api/jobs/{job['id']}").json()
        if it["state"] == "error":
            break
        time.sleep(0.05)
    assert it["error"].startswith("LibreOffice non ha prodotto")
    en = client.get(f"/api/jobs/{job['id']}", headers={"Accept-Language": "en"}).json()
    assert en["error"] == "LibreOffice did not produce the file (unrecognised format or damaged file)"


def test_pages_load_the_dictionary(client):
    for url in ("/", "/admin"):
        html = client.get(url).text
        assert '<script src="static/i18n.js"></script>' in html
        assert "data-lang-switch" in html
    r = client.get("/static/i18n.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "UC_I18N" in r.text


def test_dictionary_covers_pdf_tools():
    """Ogni testo che l'API manda per gli strumenti PDF ha la sua traduzione nella pagina."""
    from converter import pdftools
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    texts = set()
    for t in pdftools.TOOLS:
        texts |= {t.title, t.description, t.action}
        for o in t.options:
            texts.add(o["label"])
            texts |= {c[1] for c in o.get("choices", [])}
    missing = [s for s in texts if f'"{s}"' not in js]
    assert not missing, missing


def test_docs_language(client, tmp_path, monkeypatch):
    import converter.app as app_mod
    (tmp_path / "docs-it.html").write_text("IT")
    (tmp_path / "docs-en.html").write_text("EN")
    monkeypatch.setattr(app_mod, "STATIC", tmp_path)
    with TestClient(create_app(Settings(work_dir=tmp_path / "w"), Graph(), pdf_tools={})) as c:
        assert c.get("/docs").text == "IT"
        assert c.get("/docs", headers={"Accept-Language": "en-GB"}).text == "EN"
        assert c.get("/docs?lang=it", headers={"Accept-Language": "en-GB"}).text == "IT"
        assert c.get("/docs?lang=en").text == "EN"
