"""PDF -> Word o PowerPoint "identico all'originale": ogni pagina diventa un'immagine.

Il testo non e' piu' modificabile, ma l'aspetto e' esattamente quello del PDF: utile per le slide e per i PDF
impaginati con cura, che pdf2docx ricostruisce male (caratteri sostituiti, testo che esce dalle caselle).
Gira in un processo separato, con un tempo massimo, come pdf2docx:

    python3 pageimages.py docx|pptx in.pdf out.docx [dpi]
"""
from __future__ import annotations

import io
import sys

EMU_PER_PT = 12700
MAX_PIXELS = 5000  # lato lungo massimo di ogni immagine


def render(pdf: str, dpi: int):
    """(larghezza in punti, altezza in punti, PNG) per ogni pagina."""
    import pymupdf  # arriva con pdf2docx

    with pymupdf.open(pdf) as doc:
        if doc.page_count == 0:
            raise SystemExit("nessuna pagina nel PDF")
        for page in doc:
            r = page.rect
            # pagine enormi (14.400 punti...): al massimo MAX_PIXELS per lato, altrimenti miliardi di pixel
            d = max(1, min(dpi, int(MAX_PIXELS * 72 / max(r.width, r.height, 1))))
            yield r.width, r.height, page.get_pixmap(dpi=d).tobytes("png")


def to_docx(pages, out: str) -> None:
    """Una sezione per pagina, con le misure della pagina e margini a zero; l'immagine riempie la pagina."""
    import copy

    from docx import Document
    from docx.shared import Emu

    doc = Document()
    for w, h, png in pages:
        if doc.paragraphs:
            # chiude la pagina precedente: una copia della sezione finale (con le sue misure) va nel suo paragrafo,
            # cosi' non servono paragrafi vuoti che finirebbero su una pagina in piu'
            doc.paragraphs[-1]._p.get_or_add_pPr().append(copy.deepcopy(doc.sections[-1]._sectPr))
        sect = doc.sections[-1]  # la sezione finale del documento: d'ora in poi descrive questa pagina
        sect.orientation = 1 if w > h else 0
        sect.page_width, sect.page_height = Emu(int(w * EMU_PER_PT)), Emu(int(h * EMU_PER_PT))
        for side in ("left_margin", "right_margin", "top_margin", "bottom_margin", "header_distance",
                     "footer_distance", "gutter"):
            setattr(sect, side, Emu(0))
        par = doc.add_paragraph()
        fmt = par.paragraph_format
        fmt.space_before = fmt.space_after = Emu(0)
        fmt.line_spacing = 1.0
        par.add_run().add_picture(io.BytesIO(png), width=Emu(int(w * EMU_PER_PT)), height=Emu(int(h * EMU_PER_PT)))
    doc.core_properties.author = ""
    doc.core_properties.comments = ""
    doc.save(out)


def to_pptx(pages, out: str) -> None:
    """Una slide per pagina; la dimensione delle slide e' quella della prima pagina, le altre vengono adattate."""
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation()
    blank = prs.slide_layouts[6]
    for i, (w, h, png) in enumerate(pages):
        if i == 0:
            prs.slide_width, prs.slide_height = Emu(int(w * EMU_PER_PT)), Emu(int(h * EMU_PER_PT))
        sw, sh = prs.slide_width, prs.slide_height
        scale = min(sw / (w * EMU_PER_PT), sh / (h * EMU_PER_PT))
        pw, ph = int(w * EMU_PER_PT * scale), int(h * EMU_PER_PT * scale)
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(io.BytesIO(png), Emu((sw - pw) // 2), Emu((sh - ph) // 2), Emu(pw), Emu(ph))
    prs.save(out)


def main(argv: list[str]) -> None:
    kind, pdf, out = argv[:3]
    dpi = int(argv[3]) if len(argv) > 3 else 150
    pages = render(pdf, dpi)
    (to_docx if kind == "docx" else to_pptx)(pages, out)


if __name__ == "__main__":
    main(sys.argv[1:])
