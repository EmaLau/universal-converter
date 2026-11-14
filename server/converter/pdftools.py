"""Strumenti PDF in stile iLovePDF: unire, dividere, estrarre o togliere pagine, ruotare, comprimere, OCR.

A differenza delle conversioni (un file -> un formato) uno strumento riceve uno o piu' PDF e delle opzioni.
Firma comune: ``async def tool(job, inputs, opts, wd) -> (risultato, nome del file da scaricare)``
  inputs  i PDF caricati, nell'ordine in cui sono arrivati
  opts    opzioni gia' controllate da ``PdfTool.parse``
  wd      cartella vuota in cui scrivere il risultato
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from .formats import stem_of
from .runner import ConvError, run, zip_many
from .tools import pdf_page_count

if TYPE_CHECKING:
    from .jobs import Job

ToolFn = Callable[["Job", list[Path], dict, Path], Awaitable[tuple[Path, str]]]
MAX_FILES = 50
_RANGE = re.compile(r"^(\d+)?(-)?(\d+)?$")
_LANG = re.compile(r"^[a-z_]{3,10}(\+[a-z_]{3,10}){0,4}$")


class OptionError(ValueError):
    """Opzione non valida: il messaggio viene mostrato all'utente (HTTP 400)."""


# ------------------------------------------------------------------------------------- intervalli di pagine
def parse_ranges(text: str, total: int | None = None) -> list[tuple[int, int | None]]:
    """"1-3, 5, 8-" -> [(1, 3), (5, 5), (8, None)]; None = fino all'ultima pagina.

    Con ``total`` controlla anche che le pagine esistano e sostituisce None con l'ultima pagina.
    """
    out: list[tuple[int, int | None]] = []
    for part in re.split(r"[,;\s]+", re.sub(r"\s*-\s*", "-", text.strip())):
        if not part:
            continue
        m = _RANGE.match(part)
        if not m or not (m.group(1) or m.group(3)):
            raise OptionError(f"intervallo di pagine non valido: '{part}' (esempio: 1-3, 5, 8-)")
        a, dash, b = m.groups()
        start = int(a) if a else 1
        end = (int(b) if b else None) if dash else start
        if start < 1 or (end is not None and end < start):
            raise OptionError(f"intervallo di pagine non valido: '{part}'")
        if total is not None:
            end = total if end is None else end
            if end > total:
                raise OptionError(f"il PDF ha {total} pagine: '{part}' va oltre")
        out.append((start, end))
    if not out:
        raise OptionError("indica almeno una pagina (esempio: 1-3, 5)")
    return out


def qpdf_ranges(ranges: list[tuple[int, int | None]]) -> str:
    return ",".join(f"{a}" if a == b else f"{a}-{b if b is not None else 'z'}" for a, b in ranges)


def complement(ranges: list[tuple[int, int | None]], total: int) -> list[tuple[int, int]]:
    """Pagine NON comprese negli intervalli, come intervalli."""
    drop = {p for a, b in ranges for p in range(a, (b or total) + 1)}
    keep, out = [p for p in range(1, total + 1) if p not in drop], []
    for p in keep:
        if out and out[-1][1] == p - 1:
            out[-1] = (out[-1][0], p)
        else:
            out.append((p, p))
    return out


# ------------------------------------------------------------------------------------------------ strumenti
async def merge(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    out = wd / "out.pdf"
    await run(["qpdf", "--empty", "--pages", *map(str, inputs), "--", str(out)], timeout=1800)
    return out, f"{stem_of(job.filename)}-unito.pdf"


async def split(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    """Senza intervalli: un PDF per pagina. Con intervalli: un PDF per intervallo. Risultato in uno zip."""
    src, stem = inputs[0], stem_of(job.filename)
    parts = wd / "parts"
    parts.mkdir()
    total = await pdf_page_count(src)
    if not opts["pages"]:
        if total < 2:
            raise ConvError("il PDF ha una sola pagina: non c'e' niente da dividere")
        await run(["qpdf", "--split-pages", str(src), str(parts / f"{stem}-pagina.pdf")], timeout=1800)
    else:
        ranges = parse_ranges(opts["pages"], total)
        for i, r in enumerate(ranges, 1):
            job.progress = (i - 1) / len(ranges)
            name = f"{stem}-{r[0]}" + (f"-{r[1]}" if r[1] != r[0] else "") + ".pdf"
            await run(["qpdf", str(src), "--pages", str(src), qpdf_ranges([r]), "--", str(parts / name)],
                      timeout=900)
    files = sorted(parts.iterdir())
    if len(files) == 1:
        return files[0], files[0].name
    return zip_many(files, wd / "parti.zip"), f"{stem}-diviso.zip"


async def extract(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    src, out = inputs[0], wd / "out.pdf"
    ranges = parse_ranges(opts["pages"], await pdf_page_count(src))
    await run(["qpdf", str(src), "--pages", str(src), qpdf_ranges(ranges), "--", str(out)], timeout=900)
    return out, f"{stem_of(job.filename)}-estratto.pdf"


async def remove(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    src, out = inputs[0], wd / "out.pdf"
    total = await pdf_page_count(src)
    keep = complement(parse_ranges(opts["pages"], total), total)
    if not keep:
        raise ConvError("non puoi togliere tutte le pagine")
    await run(["qpdf", str(src), "--pages", str(src), qpdf_ranges(keep), "--", str(out)], timeout=900)
    return out, f"{stem_of(job.filename)}-senza-pagine.pdf"


async def rotate(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    src, out = inputs[0], wd / "out.pdf"
    spec = f"+{opts['angle']}"
    if opts["pages"]:
        spec += ":" + qpdf_ranges(parse_ranges(opts["pages"], await pdf_page_count(src)))
    await run(["qpdf", str(src), str(out), f"--rotate={spec}"], timeout=900)
    return out, f"{stem_of(job.filename)}-ruotato.pdf"


COMPRESS_LEVELS = {"low": "/printer", "medium": "/ebook", "high": "/screen"}


async def compress(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    """Ghostscript ricomprime le immagini; se il risultato non e' piu' piccolo si tiene l'originale."""
    src, out = inputs[0], wd / "out.pdf"
    await run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6",
               f"-dPDFSETTINGS={COMPRESS_LEVELS[opts['level']]}", "-dDetectDuplicateImages=true",
               "-dCompressFonts=true", f"-sOutputFile={out}", str(src)], timeout=3600)
    before, after = src.stat().st_size, out.stat().st_size if out.exists() else 0
    if not after or after >= before:
        shutil.copy(src, out)
        job.note = "il PDF era gia' compresso: hai ricevuto l'originale"
    else:
        job.note = f"dimensione ridotta del {round(100 * (1 - after / before))}%"
    return out, f"{stem_of(job.filename)}-compresso.pdf"


async def ocr(job: Job, inputs: list[Path], opts: dict, wd: Path) -> tuple[Path, str]:
    """Aggiunge il testo riconosciuto sotto le immagini delle pagine: il PDF diventa ricercabile e copiabile."""
    src, out = inputs[0], wd / "out.pdf"
    mode = "--force-ocr" if opts["force"] else "--skip-text"  # di base non tocca le pagine che hanno gia' testo
    await run(["ocrmypdf", "-q", "-l", opts["lang"], mode, "--rotate-pages", "--jobs", "2",
               "--output-type", "pdf", str(src), str(out)], timeout=4 * 3600)
    return out, f"{stem_of(job.filename)}-ocr.pdf"


# --------------------------------------------------------------------------------------------- definizioni
@dataclass(frozen=True)
class PdfTool:
    name: str
    title: str
    description: str
    action: str                 # testo del pulsante
    fn: ToolFn
    needs: tuple[str, ...] = ("qpdf",)
    min_files: int = 1
    max_files: int = 1
    options: tuple[dict, ...] = field(default_factory=tuple)

    def parse(self, form: dict[str, str]) -> dict:
        """Controlla le opzioni ricevute; solleva OptionError con un messaggio comprensibile."""
        opts: dict = {}
        for o in self.options:
            raw = (form.get(o["name"]) or "").strip()
            if o["type"] == "pages":
                if raw:
                    parse_ranges(raw)  # solo la sintassi: le pagine si controllano quando si apre il PDF
                elif o.get("required"):
                    raise OptionError(f"indica le pagine ({o['label'].lower()})")
                opts[o["name"]] = raw
            elif o["type"] == "select":
                raw = raw or o["default"]
                if raw not in [c[0] for c in o["choices"]]:
                    raise OptionError(f"valore non valido per '{o['label']}': {raw}")
                opts[o["name"]] = raw
            elif o["type"] == "bool":
                opts[o["name"]] = raw.lower() in ("1", "true", "on", "yes", "si")
            elif o["type"] == "lang":
                raw = (raw or o["default"]).lower()
                if not _LANG.match(raw):
                    raise OptionError("lingue non valide: usa i codici di Tesseract, per esempio ita+eng")
                opts[o["name"]] = raw
        if opts.get("angle"):
            opts["angle"] = int(opts["angle"])
        return opts

    def public(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description, "action": self.action,
                "min_files": self.min_files, "max_files": self.max_files, "options": list(self.options)}


PAGES_OPT = {"name": "pages", "type": "pages", "label": "Pagine", "placeholder": "1-3, 5, 8-"}
TOOLS = (
    PdfTool("merge", "Unisci PDF", "Più PDF in uno solo, nell'ordine scelto", "Unisci", merge,
            min_files=2, max_files=MAX_FILES),
    PdfTool("split", "Dividi PDF", "Un PDF per pagina o per intervallo", "Dividi", split,
            options=({**PAGES_OPT, "label": "Intervalli (vuoto = una pagina per file)"},)),
    PdfTool("extract", "Estrai pagine", "Un nuovo PDF con le pagine scelte", "Estrai", extract,
            options=({**PAGES_OPT, "required": True},)),
    PdfTool("remove", "Togli pagine", "Elimina le pagine che non servono", "Togli le pagine", remove,
            options=({**PAGES_OPT, "required": True},)),
    PdfTool("rotate", "Ruota PDF", "Raddrizza tutte le pagine o solo alcune", "Ruota", rotate,
            options=({"name": "angle", "type": "select", "label": "Rotazione", "default": "90",
                      "choices": [["90", "90° in senso orario"], ["180", "180°"], ["270", "90° in senso antiorario"]]},
                     {**PAGES_OPT, "label": "Pagine (vuoto = tutte)"})),
    PdfTool("compress", "Comprimi PDF", "Riduci il peso ricomprimendo le immagini", "Comprimi", compress,
            needs=("gs",),
            options=({"name": "level", "type": "select", "label": "Compressione", "default": "medium",
                      "choices": [["low", "Bassa (qualità di stampa)"], ["medium", "Media (consigliata)"],
                                  ["high", "Alta (file più piccolo)"]]},)),
    PdfTool("ocr", "OCR PDF", "Rendi ricercabile il testo delle scansioni", "Riconosci il testo", ocr,
            needs=("ocrmypdf",),
            options=({"name": "lang", "type": "lang", "label": "Lingue", "default": "ita+eng",
                      "placeholder": "ita+eng"},
                     {"name": "force", "type": "bool", "label": "Rifai l'OCR anche sulle pagine che hanno già testo"})),
)


def available_tools() -> dict[str, PdfTool]:
    """Solo gli strumenti i cui programmi sono installati (fuori dal container alcuni possono mancare)."""
    return {t.name: t for t in TOOLS if all(shutil.which(n) for n in t.needs)}
