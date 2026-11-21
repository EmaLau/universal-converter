"""La pagina web in un browser vero (Playwright): schede, file, cartelle, menu, opzioni, conversione, lingua.

Si salta se Playwright non c'e'. In GitHub Actions usa il Chromium di Playwright; in locale si puo' usare Chrome
con UI_BROWSER_CHANNEL=chrome. I convertitori sono finti (nessun programma esterno), il grafo e' quello vero.
"""
import os
import socket
import threading
import time
import zipfile
from io import BytesIO

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
uvicorn = pytest.importorskip("uvicorn")

from converter.app import create_app  # noqa: E402
from converter.config import Settings  # noqa: E402
from converter.graph import default_graph  # noqa: E402

from test_api import upper  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    g = default_graph()
    # convertitori finti per le conversioni provate (i menu restano quelli veri)
    g.edges = [e if (e.src, e.dst) not in {("txt", "md"), ("md", "html")} else e.__class__(e.src, e.dst, upper, "Test")
               for e in g.edges]
    g.add("txt", "md", upper, "Test", cost=0.1)
    g.rebuild()
    app = create_app(Settings(work_dir=tmp_path_factory.mktemp("work"), plico_url=":30128"), g)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        channel = os.environ.get("UI_BROWSER_CHANNEL") or None
        b = p.chromium.launch(channel=channel)
        yield b
        b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(locale="it-IT", accept_downloads=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text
          else None)
    pg.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    pg.goto(server + "/")
    pg.wait_for_selector("#grid .tool")
    yield pg
    ctx.close()
    assert errors == [], errors


def open_any(page):
    """Apre "Qualsiasi formato" e aspetta l'area di lavoro (prima non si possono aggiungere file)."""
    page.locator("#grid .tool.any").click()
    expect(page.locator("#work")).to_be_visible()


def files(*items):
    return [{"name": n, "mimeType": "application/octet-stream", "buffer": b} for n, b in items]


def test_cards(page):
    cards = page.locator("#grid .tool b").all_inner_texts()
    for name in ("Qualsiasi formato", "PDF in Word", "PDF in PowerPoint", "Tabelle PDF in Excel", "Email in PDF",
                 "Diagrammi in SVG", "Immagini da un PDF", "Altri strumenti PDF in Plico"):
        assert name in cards, name
    assert page.locator("a.tool[href$='#estraiimg']").count() == 1


def test_convert_and_download_all_keeps_folders(page, server, tmp_path):
    (tmp_path / "Corso" / "Lezioni").mkdir(parents=True)
    (tmp_path / "Corso" / "Lezioni" / "a.txt").write_text("uno")
    (tmp_path / "Corso" / "b.txt").write_text("due")
    (tmp_path / "Corso" / ".DS_Store").write_text("x")  # file nascosto: va ignorato
    open_any(page)
    page.set_input_files("#dirinput", tmp_path / "Corso")
    expect(page.locator("#files .fname")).to_have_count(2)
    assert sorted(page.locator("#files .fname").all_inner_texts()) == ["Corso/Lezioni/a.txt", "Corso/b.txt"]
    page.select_option("#all", "md")
    page.click("#go")
    expect(page.locator("#files .ok")).to_have_count(2, timeout=15000)
    with page.expect_download() as dl:
        page.click("#dlall")
    with zipfile.ZipFile(BytesIO(open(dl.value.path(), "rb").read())) as z:
        assert sorted(z.namelist()) == ["Corso/Lezioni/a.md", "Corso/b.md"]


def test_menus_and_options(page):
    open_any(page)
    page.set_input_files("#input", files(("foto.zip", b"PK\x05\x06" + b"\x00" * 18), ("slide.pdf", b"%PDF-1.4"),
                                         ("schema.dot", b"digraph { a -> b }"), ("film.mov", b"x")))
    expect(page.locator("#files select")).to_have_count(4)
    menus = [s.locator("option").all_inner_texts() for s in page.locator("#files select").all()]
    assert any(t.startswith("Ogni file in PDF") for t in menus[0])  # conversione in blocco
    assert any("PPTX" in t for t in menus[1])
    assert page.locator("#files .fname").nth(2).inner_text() == "schema.gv"  # .dot di Graphviz riconosciuto
    # PDF -> Word: Impaginazione; video -> MP4: sottotitoli da aggiungere
    page.locator("#files select").nth(1).select_option("docx")
    expect(page.locator("#copts")).to_contain_text("Impaginazione")
    page.locator("#files select").nth(3).select_option("mp4")
    expect(page.locator("#copts")).to_contain_text("Sottotitoli da aggiungere")
    presets = page.locator("#copts select").first.locator("option").all_inner_texts()
    assert "Word identico al PDF" in presets


def test_english(page):
    page.locator("button:has-text('EN')").first.click()
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#grid .tool b", has_text="PDF to PowerPoint")).to_have_count(1)
    open_any(page)
    page.set_input_files("#input", files(("foto.zip", b"PK\x05\x06" + b"\x00" * 18)))
    expect(page.locator("#files select")).to_have_count(1)
    assert any(t.startswith("Every file to PDF") for t in page.locator("#files select option").all_inner_texts())
    assert page.locator("#pickdir").inner_text() == "A folder"
