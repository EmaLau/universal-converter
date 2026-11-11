"""Grafo delle conversioni.

Ogni convertitore e' un arco "estensione -> estensione". Per ogni formato di partenza si cerca il percorso
piu' economico (al massimo MAX_HOPS passaggi) verso tutti gli altri: md -> pdf, per esempio, diventa
Pandoc (md -> docx) + LibreOffice (docx -> pdf).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Iterable

from . import tools
from .formats import ALIASES, CATEGORY_OF, ORDER, category, normalize

if TYPE_CHECKING:
    from pathlib import Path

    from .jobs import Job

Converter = Callable[["Job", "Path", str, "Path"], Awaitable["Path"]]
MAX_HOPS = 3


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    fn: Converter
    tool: str
    cost: float = 1.0
    source_only: bool = False  # solo se e' il formato originale (pdf -> docx da un PDF "vero")
    final_only: bool = False   # produce piu' file (zip): niente passaggi dopo


def is_sensible(src: str, dst: str) -> bool:
    """Toglie le combinazioni possibili ma inutili (foglio di calcolo -> MP3, xlsx -> docx...)."""
    a, b = category(src), category(dst)
    closed = ("Sottotitoli", "Font")  # categorie che non si mescolano con le altre
    rules = (
        (a in closed or b in closed) and a != b,
        a == "Dati" and b not in ("Dati", "Foglio di calcolo"),
        b == "Dati" and a not in ("Dati", "Foglio di calcolo"),
        a == "Audio" and b != "Audio",
        a == "Video" and b not in ("Video", "Audio") and dst != "gif",
        a == "Disegno" and b not in ("Immagine", "Disegno") and dst != "pdf",
        a in ("Foglio di calcolo", "Presentazione") and b == "Ebook",
        src == "xopp" and dst not in ("pdf", "jpg", "png"),
        a == "Archivio" and b != "Archivio",
        b == "Archivio" and a != "Archivio",
        a == "Foglio di calcolo" and b == "Documento" and dst not in ("pdf", "html", "txt", "md"),
        a == "Foglio di calcolo" and b == "Presentazione",
        b == "Presentazione" and a == "Documento" and src not in ("md", "rst", "org", "html", "textile"),
        a == "Presentazione" and b == "Documento" and dst != "pdf",
        a == "Immagine" and b != "Immagine" and dst != "pdf" and not (src in ("gif", "apng") and dst in ("mp4", "webm")),
    )
    return not any(rules)


class Graph:
    def __init__(self, max_hops: int = MAX_HOPS):
        self.max_hops = max_hops
        self.edges: list[Edge] = []
        self.disabled: set[tuple[str, str]] = set()
        self.plans: dict[str, dict[str, list[Edge]]] = {}

    def add(self, srcs: str, dsts: str, fn: Converter, tool: str, **kw) -> None:
        """Aggiunge un arco per ogni coppia: add("png jpg", "pdf", ...)."""
        for s in srcs.split():
            for d in dsts.split():
                if s != d:
                    self.edges.append(Edge(s, d, fn, tool, **kw))

    def disable(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Toglie singoli archi (es. un codec che manca nell'immagine) e ricalcola i percorsi."""
        self.disabled |= {(normalize(a), normalize(b)) for a, b in pairs}
        self.rebuild()

    def _shortest(self, src: str) -> dict[str, list[Edge]]:
        """Dijkstra: percorso piu' economico verso ogni formato raggiungibile da src."""
        best: dict[str, list[Edge]] = {}
        heap: list[tuple[float, int, str, list[Edge]]] = [(0.0, 0, src, [])]
        seen: dict[str, float] = {}
        counter = 0
        while heap:
            cost, _, node, path = heapq.heappop(heap)
            if node in seen and seen[node] <= cost:
                continue
            seen[node] = cost
            if path:
                best.setdefault(node, path)
                if path[-1].final_only:
                    continue
            if len(path) >= self.max_hops:
                continue
            for e in self.edges:
                if e.src != node or e.dst == src or (e.src, e.dst) in self.disabled or (e.source_only and path):
                    continue
                counter += 1
                heapq.heappush(heap, (cost + e.cost, counter, e.dst, path + [e]))
        return best

    def rebuild(self) -> None:
        self.plans = {src: {d: p for d, p in self._shortest(src).items() if is_sensible(src, d)}
                      for src in {e.src for e in self.edges}}

    def plan(self, src: str, dst: str) -> list[Edge] | None:
        return self.plans.get(normalize(src), {}).get(normalize(dst))

    def targets(self, src: str) -> list[str]:
        return sorted(self.plans.get(normalize(src), {}), key=lambda d: ORDER.get(d, 999))

    def payload(self) -> dict:
        """Tabella dei formati per la pagina web e per l'app Nextcloud."""
        inputs = {s: self.targets(s) for s, p in self.plans.items() if p}
        for alias, real in ALIASES.items():
            if real in inputs:
                inputs.setdefault(alias, inputs[real])
        return {"inputs": dict(sorted(inputs.items())), "categories": CATEGORY_OF,
                "tools": sorted({e.tool for e in self.edges})}


WRITER = "doc docx odt rtf txt pages wpd wps fodt abw sxw lwp hwp"
CALC = "xls xlsx ods csv tsv numbers fods xlsb sxc dif slk dbf wk1"
IMPRESS = "ppt pptx odp key fodp sxi"
DRAW = "vsd vsdx odg pub cdr wmf emf"
IMG_IN = "jpg png webp gif bmp tiff heic avif ico psd tga ppm pbm pgm pnm pcx dds hdr xcf xpm apng jp2 qoi"
IMG_OUT = "jpg png webp gif bmp tiff heic avif ico jp2 qoi tga"
RAW = "dng cr2 cr3 nef arw raf orf rw2"
AUDIO = "mp3 m4a wav flac ogg opus aac wma aiff amr mka ac3 dts ape wv caf au mp2 tta"
AUDIO_OUT = "mp3 m4a wav flac ogg opus aac aiff wma ac3 mka"
VIDEO = "mp4 mkv mov webm avi wmv flv m4v 3gp mts mpg ts ogv vob mxf asf rm rmvb f4v divx dv"
VIDEO_OUT = "mp4 mkv mov webm avi m4v wmv flv 3gp mpg ts ogv"
SUBTITLES = "srt vtt ass ssa"
EBOOK = "epub mobi azw3 azw fb2 lit pdb htmlz txtz lrf cbz cbr cb7 chm snb tcr pml"
EBOOK_OUT = "epub mobi azw3 pdf txt docx fb2 htmlz txtz lit lrf pdb"
MARKUP = "md rst org tex html ipynb textile dbk wiki opml t2t typ"
MARKUP_OUT = "docx odt html md rst tex txt epub adoc typ dbk wiki org textile texi"
ARCHIVE = "zip 7z rar tar tar.gz tar.xz tar.bz2 tar.zst iso cab cpio lha"
ARCHIVE_OUT = "zip 7z tar.gz tar.xz tar.bz2 tar.zst tar"


def default_graph(disabled: Iterable[tuple[str, str]] = ()) -> Graph:
    g = Graph()
    # documenti, fogli di calcolo, presentazioni, disegni
    # niente txt da LibreOffice: con le tabelle l'esportazione Text di LO 25.2 entra in un ciclo infinito
    g.add(WRITER, "pdf docx odt rtf doc html epub", tools.libreoffice, "LibreOffice")
    g.add(CALC, "pdf xlsx ods xls csv tsv html", tools.libreoffice, "LibreOffice")
    g.add(IMPRESS, "pdf pptx odp ppt", tools.libreoffice, "LibreOffice")
    g.add(DRAW, "pdf odg", tools.libreoffice, "LibreOffice")
    g.add(MARKUP, MARKUP_OUT, tools.pandoc, "Pandoc")
    g.add("docx odt epub", "md rst tex html adoc typ dbk wiki org textile", tools.pandoc, "Pandoc", cost=1.5)
    g.add("docx odt", "txt", tools.pandoc, "Pandoc")
    g.add("md rst org html textile", "pptx", tools.pandoc, "Pandoc", source_only=True)  # slide dai titoli
    g.add("csv tsv", "md", tools.pandoc, "Pandoc")
    g.add("xopp", "pdf", tools.xournalpp, "Xournal++")
    # PDF e PostScript
    g.add("pdf", "docx", tools.pdf_to_docx, "pdf2docx", source_only=True)
    g.add("pdf", "txt", tools.pdf_to_text, "Poppler")
    g.add("pdf", "html", tools.pdf_to_html, "Poppler", cost=1.2)
    g.add("pdf", "jpg png", tools.pdf_to_images, "Poppler", final_only=True)
    g.add("pdf", "svg", tools.pdf_to_svg, "Poppler", final_only=True)
    g.add("ps eps", "pdf", tools.ghostscript_pdf, "Ghostscript")
    # immagini
    g.add(IMG_IN, IMG_OUT, tools.imagemagick, "ImageMagick")
    g.add("eps ps", "png jpg", tools.imagemagick, "ImageMagick", cost=1.5)
    g.add("jpg png tiff", "pdf", tools.image_to_pdf, "img2pdf")
    g.add("svg", "png pdf", tools.svg_render, "librsvg")
    g.add(RAW, "tiff", tools.raw_develop, "LibRaw")
    # audio, video, sottotitoli
    g.add(AUDIO, AUDIO_OUT, tools.ffmpeg, "FFmpeg")
    g.add(VIDEO, f"{VIDEO_OUT} gif {AUDIO_OUT}", tools.ffmpeg, "FFmpeg")
    g.add("gif apng", "mp4 webm", tools.ffmpeg, "FFmpeg")
    g.add(SUBTITLES, "srt vtt ass", tools.subtitles, "FFmpeg")
    # ebook
    g.add(EBOOK, EBOOK_OUT, tools.calibre, "Calibre", cost=1.2)
    g.add("pdf", "epub", tools.calibre, "Calibre", cost=1.2)
    # dati, font, archivi
    g.add("json yaml toml csv tsv", "json yaml", tools.data, "Python")
    g.add("json yaml toml", "csv", tools.data, "Python")
    g.add("ttf otf", "woff woff2", tools.font, "fontTools")
    # da WOFF il formato giusto (TTF o OTF) dipende dai contorni del font: solo dal file originale, mai a catena
    g.add("woff woff2", "ttf otf woff woff2", tools.font, "fontTools", source_only=True)
    g.add(ARCHIVE, ARCHIVE_OUT, tools.archive, "libarchive")
    g.disable(disabled)  # calcola anche i percorsi
    return g
