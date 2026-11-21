"""PDF di slide: PDF -> PowerPoint, impaginazione «Identica» per Word e PowerPoint, avviso sulle presentazioni."""
import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from converter import options, tools
from converter.graph import default_graph

PAGEIMAGES = Path(tools.__file__).with_name("pageimages.py")


def tools_of(plan):
    return [(e.tool, e.src, e.dst) for e in plan]


def test_pdf_to_pptx_only_from_original_pdf():
    g = default_graph()
    assert tools_of(g.plan("pdf", "pptx")) == [("LibreOffice", "pdf", "pptx")]
    assert tools_of(g.plan("pdf", "odp")) == [("LibreOffice", "pdf", "pptx"), ("LibreOffice", "pptx", "odp")]
    assert g.plan("docx", "pptx") is None  # mai docx -> pdf -> pptx
    assert tools_of(g.plan("md", "pptx")) == [("Pandoc", "md", "pptx")]
    assert g.plan("ps", "pptx") is None  # dopo Ghostscript il PDF non e' piu' l'originale


def test_layout_option():
    g = default_graph()
    assert options.applicable(g.plan("pdf", "docx"), "docx") == ["layout"]
    assert options.applicable(g.plan("pdf", "pptx"), "pptx") == ["layout"]
    assert options.applicable(g.plan("pdf", "odp"), "odp") == []
    assert options.parse({"layout": "exact"}, g.plan("pdf", "docx"), "docx") == {"layout": "exact"}
    assert options.parse({"layout": ""}, g.plan("pdf", "pptx"), "pptx") == {}
    with pytest.raises(options.OptionError, match="non valido"):
        options.parse({"layout": "boh"}, g.plan("pdf", "docx"), "docx")
    with pytest.raises(options.OptionError, match="non disponibile"):
        options.parse({"layout": "exact"}, g.plan("docx", "pdf"), "pdf")


@pytest.mark.parametrize("info, slides", [
    ("Creator:         Microsoft® PowerPoint® per Microsoft 365\nPage size:       720 x 540 pts\n", True),
    ("Producer:        Keynote\nPage size:       595 x 842 pts (A4)\n", True),
    ("Creator:         Writer\nProducer:        LibreOffice 25.2\nPage size:       960 x 540 pts\n", True),  # 16:9
    ("Creator:         LaTeX with Beamer class\nPage size:       362.83 x 272.13 pts\n", True),
    ("Creator:         Writer\nPage size:       595.276 x 841.89 pts (A4)\n", False),
    ("Creator:         Word\nPage size:       841.89 x 595.276 pts (A4)\n", False),  # A4 orizzontale: non e' una slide
    ("", False),
])
def test_slides_from_info(info, slides):
    assert tools.slides_from_info(info) is slides


def run_converter(fn, tmp_path, monkeypatch, opts, slides):
    calls = []

    async def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "pdfinfo":
            return "Creator: PowerPoint\n" if slides else "Creator: Writer\nPage size: 595 x 842 pts\n"
        if cmd[0] == "soffice":
            (tmp_path / "in.pptx").write_bytes(b"pptx")
        return ""

    monkeypatch.setattr(tools, "run", fake_run)
    job = SimpleNamespace(options=opts, target=fn.__name__[-4:], note="", step="", dir=tmp_path)
    asyncio.run(fn(job, tmp_path / "in.pdf", job.target, tmp_path))
    return job, calls


def test_docx_editable_warns_on_slides(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "AUTO_OCR", False)  # qui conta solo l'avviso (l'OCR ha i suoi test)
    job, calls = run_converter(tools.pdf_to_docx, tmp_path, monkeypatch, {}, slides=True)
    assert "pdf2docx" in calls[0][2] and calls[1][0] == "pdfinfo"
    assert job.note.startswith("sembra una presentazione")
    job, _ = run_converter(tools.pdf_to_docx, tmp_path, monkeypatch, {}, slides=False)
    assert job.note == ""


def test_exact_layout_uses_page_images(tmp_path, monkeypatch):
    for fn, kind in ((tools.pdf_to_docx, "docx"), (tools.pdf_to_pptx, "pptx")):
        job, calls = run_converter(fn, tmp_path, monkeypatch, {"layout": "exact"}, slides=True)
        assert calls == [["python3", str(PAGEIMAGES), kind, str(tmp_path / "in.pdf"), str(tmp_path / f"out.{kind}")]]
        assert job.note == ""


def test_pptx_editable_uses_libreoffice_pdf_import(tmp_path, monkeypatch):
    _, calls = run_converter(tools.pdf_to_pptx, tmp_path, monkeypatch, {}, slides=True)
    assert "--infilter=impress_pdf_import" in calls[0] and "pptx:Impress MS PowerPoint 2007 XML" in calls[0]


def test_translated_note():
    from converter.i18n import t
    assert t(tools.SLIDES_NOTE, "en").startswith("this looks like a presentation")


# ------------------------------------------------- pagine come immagini, con le librerie vere (se installate)

def test_pageimages_real(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    docx = pytest.importorskip("docx")
    pptx = pytest.importorskip("pptx")
    pdf = tmp_path / "s.pdf"
    with pymupdf.open() as doc:
        for w, h, text in ((720, 540, "Slide uno"), (595, 842, "Pagina verticale"), (720, 540, "Slide tre")):
            doc.new_page(width=w, height=h).insert_text((72, 72), text, fontsize=28)
        doc.save(pdf)
    for kind in ("docx", "pptx"):
        out = tmp_path / f"out.{kind}"
        subprocess.run([sys.executable, str(PAGEIMAGES), kind, str(pdf), str(out)], check=True)
        if kind == "docx":
            d = docx.Document(out)
            sizes = [(round(s.page_width.pt), round(s.page_height.pt)) for s in d.sections]
            assert sizes == [(720, 540), (595, 842), (720, 540)]
            assert all(s.left_margin == 0 and s.top_margin == 0 for s in d.sections)
            assert len(d.inline_shapes) == 3 and len(d.paragraphs) == 3
        else:
            p = pptx.Presentation(out)
            assert (round(p.slide_width.pt), round(p.slide_height.pt)) == (720, 540)
            assert [len(s.shapes) for s in p.slides] == [1, 1, 1]
            portrait = p.slides[1].shapes[0]
            assert portrait.height == p.slide_height and portrait.width < p.slide_width  # adattata, non deformata
