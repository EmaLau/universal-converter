"""Convertitori: ognuno trasforma un file in un altro formato con un programma esterno.

Firma comune: ``async def conv(job, inp, out_ext, wd) -> Path``
  job      il lavoro (usa ``id``, ``dir``, ``step`` e ``progress``)
  inp      file di ingresso, con l'estensione giusta
  out_ext  estensione di arrivo
  wd       cartella vuota in cui scrivere il risultato
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .formats import category, ext_of
from .runner import ConvError, run, single_output, zip_many

if TYPE_CHECKING:
    from .jobs import Job


def opts_of(job, out_ext: str) -> dict:
    """Opzioni di conversione scelte dall'utente, solo per l'ultimo passaggio (quello che crea il risultato)."""
    o = getattr(job, "options", None) or {}
    return o if o and out_ext == getattr(job, "target", out_ext) else {}


def is_final(job, out_ext: str) -> bool:
    """Questo passaggio crea il risultato (e non un file intermedio di una catena)?"""
    return out_ext == getattr(job, "target", out_ext)


def add_note(job, text: str) -> None:
    """Aggiunge una nota al risultato; piu' note sono separate da "; " (e tradotte una per una)."""
    job.note = f"{job.note}; {text}" if getattr(job, "note", "") else text


# impostazioni lette all'avvio (app.create_app -> configure)
AUTO_OCR = True
OCR_LANG = "ita+eng"


def configure(auto_ocr: bool = True, ocr_lang: str = "ita+eng") -> None:
    global AUTO_OCR, OCR_LANG
    AUTO_OCR, OCR_LANG = auto_ocr, ocr_lang

# ------------------------------------------------------------------------------------------- LibreOffice
LO_FILTERS = {
    "pdf": "pdf", "docx": "docx:MS Word 2007 XML", "odt": "odt", "rtf": "rtf", "doc": "doc:MS Word 97",
    "txt": "txt:Text", "html": "html:XHTML Writer File:UTF8", "epub": "epub",
    "xlsx": "xlsx:Calc MS Excel 2007 XML", "ods": "ods", "xls": "xls:MS Excel 97",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML", "odp": "odp", "ppt": "ppt:MS PowerPoint 97", "odg": "odg",
}
# Filtri diversi a seconda del tipo di documento di partenza: (categoria, estensione) -> (filtro, estensione creata)
LO_FILTERS_BY_KIND = {
    ("Foglio di calcolo", "html"): ("html:HTML (StarCalc)", "html"),
    ("Foglio di calcolo", "tsv"): ("csv:Text - txt - csv (StarCalc):9,34,76,1", "csv"),
}


def csv_separator(sample: str, ext: str) -> int:
    """Codice ASCII del separatore piu' probabile: tab, punto e virgola o virgola."""
    if ext == "tsv" or sample.count("\t") > max(sample.count(";"), sample.count(",")):
        return 9
    return 59 if sample.count(";") > sample.count(",") else 44


async def libreoffice(job: Job, inp: Path, out_ext: str, wd: Path, infilter: str | None = None) -> Path:
    profile = job.dir / "lo-profile"  # profilo separato per lavoro: piu' istanze in parallelo
    cmd = ["soffice", f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nolockcheck"]
    src = ext_of(inp.name)
    if infilter:
        cmd.append(f"--infilter={infilter}")
    elif src in ("csv", "tsv"):
        with inp.open("rb") as fh:
            sample = fh.read(65536).decode("utf-8", "replace")
        cmd.append(f"--infilter=CSV:{csv_separator(sample, src)},34,76,1")
    lo_filter, produced = LO_FILTERS_BY_KIND.get((category(src), out_ext), (LO_FILTERS.get(out_ext), out_ext))
    all_sheets = category(src) == "Foglio di calcolo" and produced == "csv" and is_final(job, out_ext) \
        and src not in ("csv", "tsv")
    if all_sheets:  # risultato finale in CSV: tutti i fogli, uno per file (in uno ZIP se sono piu' di uno)
        lo_filter += ",,0,false,true,false,false,false,-1"
    cmd += ["--convert-to", lo_filter, "--outdir", str(wd), str(inp)]
    try:
        for attempt in (1, 2):  # di rado soffice resta appeso all'avvio: riprova con un profilo pulito
            try:
                await run(cmd, timeout=600)
                break
            except ConvError as e:
                if attempt == 2 or "tempo scaduto" not in str(e):
                    raise
                job.step += " (nuovo tentativo)"
                shutil.rmtree(profile, ignore_errors=True)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = wd / f"{inp.stem}.{produced}"
    if all_sheets and not out.exists():
        sheets = sorted(wd.glob(f"{inp.stem}-*.csv"))
        if len(sheets) == 1:
            out = sheets[0].rename(out)
        elif sheets:
            renamed = []
            for f in sheets:  # "input-Foglio1.csv" -> "Foglio1.csv"
                renamed.append(f.rename(wd / f"{f.name[len(inp.stem) + 1:]}"))
            add_note(job, f"{len(sheets)} fogli, un CSV per foglio")
            return zip_many(renamed, wd / "out.zip")
    if not out.exists():
        raise ConvError("LibreOffice non ha prodotto il file (formato non riconosciuto o file danneggiato)")
    return out


# ------------------------------------------------------------------------------------------------- PDF
SLIDE_APPS = re.compile(r"PowerPoint|Keynote|Impress|Google (Slides|Presentazioni)|Beamer|Canva", re.I)
SLIDE_RATIOS = (4 / 3, 16 / 9, 16 / 10)
SLIDES_NOTE = ("sembra una presentazione: per modificarla conviene PowerPoint (PPTX); "
               "per un Word identico all'originale scegli Impaginazione «Identica»")


def slides_from_info(info: str) -> bool:
    """Dall'uscita di pdfinfo: creato da un programma di presentazioni, o pagine orizzontali in 4:3, 16:9, 16:10."""
    for key in ("Creator", "Producer"):
        m = re.search(rf"^{key}:\s*(.*)$", info, re.M)
        if m and SLIDE_APPS.search(m.group(1)):
            return True
    m = re.search(r"^Page size:\s*([\d.]+) x ([\d.]+)", info, re.M)
    if not m or float(m.group(2)) == 0:
        return False
    ratio = float(m.group(1)) / float(m.group(2))
    return any(abs(ratio - r) < 0.03 * r for r in SLIDE_RATIOS)


async def looks_like_slides(inp: Path) -> bool:
    try:
        return slides_from_info(await run(["pdfinfo", str(inp)], timeout=120))
    except ConvError:
        return False


async def pdf_pages_as_images(inp: Path, out: Path, kind: str) -> Path:
    """Impaginazione «Identica»: ogni pagina diventa un'immagine in Word o PowerPoint (vedi pageimages.py)."""
    script = Path(__file__).with_name("pageimages.py")
    await run(["python3", str(script), kind, str(inp), str(out)], timeout=1800, limit_memory=True)
    return out


async def pdf_to_docx(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.docx"
    if opts_of(job, out_ext).get("layout") == "exact":
        return await pdf_pages_as_images(inp, out, "docx")
    inp = await ocr_if_scan(job, inp, wd)
    code = ("import sys,logging;logging.disable(logging.WARNING);from pdf2docx import Converter;"
            "c=Converter(sys.argv[1]);c.convert(sys.argv[2]);c.close()")
    await run(["python3", "-c", code, str(inp), str(out)], timeout=1800, limit_memory=True)
    if await looks_like_slides(inp):  # pdf2docx ricostruisce male le slide: suggerisce le alternative
        add_note(job, SLIDES_NOTE)
    elif is_final(job, out_ext):
        await check_pages(job, inp, out, wd)
    return out


# ---------------------------------------------------------------- scansioni e controllo del risultato
OCR_NOTE = "era una scansione: testo riconosciuto con l'OCR"


async def is_scan(inp: Path) -> bool:
    """PDF senza testo selezionabile nelle prime pagine (meno di 20 caratteri per pagina)."""
    try:
        pages = min(5, await pdf_page_count(inp))
        text = await run(["pdftotext", "-l", str(pages), "-enc", "UTF-8", str(inp), "-"], timeout=120)
    except ConvError:
        return False
    return len(re.sub(r"\s", "", text)) < 20 * pages


async def ocr_if_scan(job: Job, inp: Path, wd: Path) -> Path:
    """OCR automatico (AUTO_OCR) prima di PDF -> Word, Excel o testo: senza, il risultato sarebbe vuoto."""
    if not AUTO_OCR or not shutil.which("ocrmypdf") or not await is_scan(inp):
        return inp
    out = wd / "ocr.pdf"
    job.step = f"OCR della scansione ({OCR_LANG})"
    try:
        await run(["ocrmypdf", "-q", "-l", OCR_LANG, "--skip-text", "--rotate-pages", "--jobs", "2",
                   "--output-type", "pdf", str(inp), str(out)], timeout=4 * 3600)
    except ConvError:
        return inp  # meglio un risultato senza OCR che nessun risultato
    add_note(job, OCR_NOTE)
    return out


def docx_saved_pages(path: Path) -> int:
    """Pagine indicate da Word in docProps/app.xml (0 se mancano: per esempio file non salvati da Word)."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            m = re.search(rb"<Pages>(\d+)</Pages>", z.read("docProps/app.xml"))
    except (OSError, KeyError, zipfile.BadZipFile):
        return 0
    return int(m.group(1)) if m else 0


def pages_differ(expected: int, got: int) -> bool:
    return expected > 0 and got > 0 and abs(got - expected) >= max(2, round(expected * 0.25))


async def check_pages(job: Job, pdf: Path, docx: Path, wd: Path) -> None:
    """PDF -> Word: impagina il Word con LibreOffice e avvisa se le pagine cambiano molto (testo che esce dalle
    caselle, caratteri sostituiti). Solo un controllo: se non riesce, il risultato resta valido."""
    check = wd / "check"
    check.mkdir(exist_ok=True)
    try:
        expected = await pdf_page_count(pdf)
        shutil.copy(docx, check / "check.docx")
        rendered = await libreoffice(job, check / "check.docx", "pdf", check)
        got = await pdf_page_count(rendered)
    except (ConvError, OSError):
        return
    finally:
        job.step = ""
    if pages_differ(expected, got):
        add_note(job, f"il PDF ha {expected} pagine, il Word se ne impagina {got}: prova Impaginazione «Identica»")
    shutil.rmtree(check, ignore_errors=True)


NO_TABLES = "nessuna tabella trovata nel PDF (se è una scansione, prima usa OCR PDF)"


async def pdf_tables(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Tabelle di un PDF in CSV, XLSX o JSON (vedi pdftables.py)."""
    out = wd / f"out.{out_ext}"
    script = Path(__file__).with_name("pdftables.py")
    try:
        inp = await ocr_if_scan(job, inp, wd)
        msg = await run(["python3", str(script), out_ext, str(inp), str(out)], timeout=1800, limit_memory=True)
    except ConvError as e:
        if "restituito 3" in str(e):
            raise ConvError(NO_TABLES) from None
        if "restituito 4" in str(e):
            raise ConvError("PDF danneggiato o non leggibile") from None
        raise
    m = re.search(r"(\d+) tabelle", msg or "")
    if m:
        n = int(m.group(1))
        add_note(job, "1 tabella trovata" if n == 1 else f"{n} tabelle trovate")
    return out


async def pdf_to_pptx(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Modificabile: LibreOffice importa ogni pagina come una slide, con le caselle di testo al loro posto."""
    if opts_of(job, out_ext).get("layout") == "exact":
        return await pdf_pages_as_images(inp, wd / "out.pptx", "pptx")
    return await libreoffice(job, inp, out_ext, wd, infilter="impress_pdf_import")


async def pdf_to_text(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.txt"
    inp = await ocr_if_scan(job, inp, wd)
    await run(["pdftotext", "-layout", "-enc", "UTF-8", str(inp), str(out)], timeout=600)
    return out


async def pdf_to_images(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Una immagine per pagina; con piu' pagine il risultato e' uno zip."""
    fmt = ["-png"] if out_ext == "png" else ["-jpeg", "-jpegopt", "quality=90"]
    o = opts_of(job, out_ext)
    rng = []
    if o.get("pages"):
        first, last = o["pages"]
        total = await pdf_page_count(inp)
        if first > total:
            raise ConvError(f"il PDF ha {total} pagine: non c'è la pagina {first}")
        rng = ["-f", str(first), "-l", str(min(last or total, total))]
    pages = wd / "pages"
    pages.mkdir()
    await run(["pdftoppm", "-r", o.get("dpi") or "150", *rng, *fmt, str(inp), str(pages / "pagina")], timeout=1800)
    files = sorted(pages.iterdir())
    if not files:
        raise ConvError("nessuna pagina nel PDF")
    return files[0] if len(files) == 1 else zip_many(files, wd / "pagine.zip")


async def pdf_page_count(inp: Path) -> int:
    out = await run(["pdfinfo", str(inp)], timeout=120)
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not m or int(m.group(1)) == 0:
        raise ConvError("nessuna pagina nel PDF")
    return int(m.group(1))


async def pdf_to_svg(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Un SVG vettoriale per pagina; con piu' pagine il risultato e' uno zip."""
    pages = wd / "pages"
    pages.mkdir()
    total = await pdf_page_count(inp)
    for n in range(1, total + 1):
        job.progress = (n - 1) / total
        await run(["pdftocairo", "-svg", "-f", str(n), "-l", str(n), str(inp), str(pages / f"pagina-{n:04d}.svg")],
                  timeout=600)
    files = sorted(pages.iterdir())
    return files[0] if len(files) == 1 else zip_many(files, wd / "pagine.zip")


async def pdf_to_html(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    await run(["pdftohtml", "-s", "-noframes", "-i", "-q", "-enc", "UTF-8", str(inp), str(wd / "out")], timeout=900)
    return single_output(wd, "*.html")


async def ghostscript_pdf(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """PostScript ed EPS in PDF (per gli EPS la pagina segue il disegno)."""
    out = wd / "out.pdf"
    await run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dEPSCrop",
               f"-sOutputFile={out}", str(inp)], timeout=900)
    return out


# ---------------------------------------------------------------------------------------------- immagini
async def imagemagick(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    from .options import magick_args
    out = wd / f"out.{out_ext}"
    o = opts_of(job, out_ext)
    src = str(inp) if out_ext in ("gif", "webp", "tiff") else f"{inp}[0]"  # animazioni e pagine multiple
    args = ["magick", src, "-auto-orient", *magick_args(o, out_ext, final=True)]
    if out_ext in ("jpg", "bmp"):  # formati senza trasparenza: sfondo bianco invece di nero
        args += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
    if out_ext == "ico":
        args += ["-resize", "256x256>", "-define", "icon:auto-resize=256,128,64,48,32,16"]
    if out_ext in ("jpg", "webp", "heic", "avif", "jxl"):
        args += ["-quality", str(o.get("quality", 90))]
    await run(args + [str(out)], timeout=900)
    return out


async def image_to_pdf(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.pdf"
    try:
        await run(["python3", "-m", "img2pdf", "--auto-orient", "-o", str(out), str(inp)], timeout=600)
    except ConvError:  # img2pdf rifiuta i PNG con trasparenza: prima la togliamo
        flat = wd / "flat.png"
        await run(["magick", f"{inp}[0]", "-background", "white", "-alpha", "remove", "-alpha", "off", str(flat)])
        await run(["python3", "-m", "img2pdf", "-o", str(out), str(flat)], timeout=600)
    return out


async def svg_render(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    await run(["rsvg-convert", "-f", out_ext, "-o", str(out), str(inp)], timeout=300)
    return out


async def raw_develop(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    local = wd / inp.name  # dcraw_emu scrive accanto al file di ingresso
    shutil.copy(inp, local)
    await run(["dcraw_emu", "-T", "-w", "-q", "3", str(local)], timeout=900)
    local.unlink()
    return single_output(wd, "*.tiff")


# -------------------------------------------------------------------------------------------- audio/video
async def ffprobe_duration(inp: Path) -> float:
    try:
        out = await run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                         "default=nw=1:nk=1", str(inp)], timeout=60)
        return float(out.strip().splitlines()[-1])
    except (ConvError, ValueError, IndexError):
        return 0.0


async def ffprobe_codecs(inp: Path) -> tuple[str, str]:
    """(codec video, codec audio) del primo flusso di ciascun tipo; stringa vuota se manca."""
    try:
        out = await run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json",
                         str(inp)], timeout=60)
        streams = json.loads(out[out.index("{"):])["streams"]
    except (ConvError, ValueError, KeyError):
        return "", ""
    v = next((s["codec_name"] for s in streams if s.get("codec_type") == "video"), "")
    a = next((s["codec_name"] for s in streams if s.get("codec_type") == "audio"), "")
    return v, a


AUDIO_ARGS = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "m4a": ["-c:a", "aac", "-b:a", "192k"],
              "aac": ["-c:a", "aac", "-b:a", "192k"], "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"],
              "ogg": ["-c:a", "libvorbis", "-q:a", "5"], "opus": ["-c:a", "libopus", "-b:a", "128k"],
              "aiff": ["-c:a", "pcm_s16be"], "wma": ["-c:a", "wmav2", "-b:a", "192k"],
              "ac3": ["-c:a", "ac3", "-b:a", "448k"], "mka": ["-c:a", "flac"]}
H264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "160k"]
FASTSTART = ["-movflags", "+faststart"]
VIDEO_ARGS = {"mp4": H264 + AAC + FASTSTART,
              "mov": H264 + AAC + FASTSTART,
              "m4v": H264 + AAC + FASTSTART,
              "mkv": H264 + AAC,
              "ts": H264 + AAC,
              "flv": H264 + AAC + ["-ar", "44100"],
              "3gp": ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-pix_fmt", "yuv420p",
                      "-vf", "scale='min(1280,iw)':-2", "-c:a", "aac", "-b:a", "96k", "-ac", "2"],
              "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                       "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"],
              "ogv": ["-c:v", "libtheora", "-q:v", "7", "-c:a", "libvorbis", "-q:a", "5"],
              "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"],
              "wmv": ["-c:v", "wmv2", "-b:v", "3M", "-c:a", "wmav2", "-b:a", "192k"],
              "mpg": ["-c:v", "mpeg2video", "-q:v", "4", "-c:a", "mp2", "-b:a", "192k"]}
COPY_H264 = {"mp4": FASTSTART, "mov": FASTSTART, "m4v": FASTSTART, "ts": [], "flv": []}  # contenitori per H.264/AAC
GIF_SECONDS = 60
GIF_FILTER = "fps=12,scale='min(640,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"


def ffmpeg_attempts(out_ext: str, vcodec: str, acodec: str, opts: dict | None = None) -> list[list[str]]:
    """Argomenti da provare in ordine: prima la copia senza ricodifica, quando il contenitore lo permette.
    Con le opzioni (taglio, risoluzione, bitrate...) si ricodifica sempre."""
    from .options import ffmpeg_output_args, reencode_needed
    opts = opts or {}
    if out_ext in AUDIO_ARGS:
        return [ffmpeg_output_args(["-vn", *AUDIO_ARGS[out_ext]], opts, out_ext)]
    if out_ext == "gif":
        limit = [] if opts.get("end") else ["-t", str(GIF_SECONDS)]
        return [ffmpeg_output_args([*limit, "-an", "-filter_complex", GIF_FILTER, "-loop", "0"], opts, out_ext)]
    attempts = [ffmpeg_output_args(VIDEO_ARGS[out_ext], opts, out_ext)]
    if reencode_needed(opts):
        return attempts
    hevc_ok = out_ext in ("mp4", "mov", "m4v", "ts")
    if out_ext in COPY_H264 and (vcodec == "h264" or (vcodec == "hevc" and hevc_ok)) and acodec in ("aac", "mp3", ""):
        attempts.insert(0, ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", *COPY_H264[out_ext]])
    elif out_ext == "mkv":  # mkv accetta quasi tutti i codec
        attempts.insert(0, ["-map", "0", "-c", "copy"])
    return attempts


async def ffmpeg(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    from .options import ffmpeg_input_args
    out = wd / f"out.{out_ext}"
    o = opts_of(job, out_ext)
    if out_ext == "gif" and o.get("end") and o["end"] - o.get("start", 0) > GIF_SECONDS:
        o = {**o, "end": o.get("start", 0) + GIF_SECONDS}  # anche con il taglio, al massimo 60 secondi di GIF
    duration = await ffprobe_duration(inp)
    if o.get("start") or o.get("end"):
        duration = max(0.0, min(duration, o.get("end") or duration) - o.get("start", 0))
    if out_ext == "gif" and not o.get("end"):
        duration = min(duration, GIF_SECONDS)
    vcodec, acodec = ("", "") if out_ext in AUDIO_ARGS or out_ext == "gif" else await ffprobe_codecs(inp)
    meta = ["-map_metadata", "-1", "-map_chapters", "-1"] if o.get("strip") else ["-map_metadata", "0"]
    base = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *ffmpeg_input_args(o), "-i", str(inp), *meta]

    def on_line(line: str):
        m = re.match(r"out_time_us=(\d+)", line)
        if m and duration > 0:
            job.progress = min(0.99, int(m.group(1)) / 1e6 / duration)

    attempts = ffmpeg_attempts(out_ext, vcodec, acodec, o)
    subs = (getattr(job, "extras", None) or {}).get("subtitles") if is_final(job, out_ext) else None
    if subs and out_ext not in AUDIO_ARGS and out_ext != "gif":
        attempts, base = with_subtitles(attempts, base, Path(subs), out_ext, bool(o.get("burn_subtitles")), job)
    err: ConvError | None = None
    for args in attempts:
        try:
            await run(base + args + ["-progress", "pipe:1", "-nostats", str(out)], timeout=4 * 3600,
                      on_line=on_line)
            return out
        except ConvError as e:
            err = e
            out.unlink(missing_ok=True)
    raise err or ConvError("ffmpeg non riuscito")


TEXT_SUBS = {"subrip", "ass", "ssa", "mov_text", "webvtt", "text"}


async def subtitle_tracks(inp: Path) -> list[tuple[int, str]]:
    """Tracce di sottotitoli testuali del video: (posizione tra i sottotitoli, lingua)."""
    try:
        out = await run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                         "stream=codec_name:stream_tags=language", "-of", "json", str(inp)], timeout=60)
        streams = json.loads(out[out.index("{"):]).get("streams", [])
    except (ConvError, ValueError):
        return []
    return [(i, (st.get("tags") or {}).get("language", "")) for i, st in enumerate(streams)
            if st.get("codec_name") in TEXT_SUBS]


def srt_to_text(srt: str) -> str:
    """Solo le battute di un SRT, senza numeri e orari."""
    lines = [ln.strip() for ln in srt.splitlines()]
    keep = [ln for ln in lines if ln and not ln.isdigit() and "-->" not in ln]
    return "\n".join(re.sub(r"<[^>]+>|\{[^}]*\}", "", ln) for ln in keep) + "\n"


def video_subtitles(transcriber=None):
    """Video -> SRT/VTT/TXT: la traccia di sottotitoli contenuta nel video (FFmpeg) e, se non c'e', la
    trascrizione con Whisper (quando WHISPER_URL e' impostato)."""
    async def convert(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
        tracks = await subtitle_tracks(inp)
        if not tracks:
            if transcriber is None:
                raise ConvError("il video non ha sottotitoli testuali; per trascrivere il parlato serve il servizio "
                                "Whisper (WHISPER_URL)")
            return await transcriber(job, inp, out_ext, wd)
        index, lang = tracks[0]
        srt = wd / "subs.srt"
        await run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(inp), "-map", f"0:s:{index}",
                   "-c:s", "srt", str(srt)], timeout=600)
        out = wd / f"out.{out_ext}"
        if out_ext == "txt":
            out.write_text(srt_to_text(srt.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        elif out_ext == "srt":
            srt.rename(out)
        else:
            await run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(srt), str(out)], timeout=300)
        add_note(job, "sottotitoli presi dal video" + (f" ({lang})" if lang else "")
                 + (f" [1/{len(tracks)}]" if len(tracks) > 1 else ""))
        return out
    convert.__name__ = "video_subtitles"
    return convert


async def graphviz(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Diagrammi Graphviz (DOT) in SVG, PNG o PDF. GV_FILE_PATH limita le immagini incluse alla cartella del lavoro."""
    out = wd / f"out.{out_ext}"
    await run(["dot", f"-T{out_ext}", "-o", str(out), str(inp)], timeout=300, limit_memory=True,
              env={"GV_FILE_PATH": str(wd), "SERVER_NAME": "converter"})
    return out


SUB_CODEC = {"mp4": "mov_text", "mov": "mov_text", "m4v": "mov_text", "mkv": "srt", "webm": "webvtt"}


def with_subtitles(attempts: list[list[str]], base: list[str], subs: Path, out_ext: str, burn: bool,
                   job=None) -> tuple[list[list[str]], list[str]]:
    """Aggiunge un file di sottotitoli al video: come traccia (si accende e spegne nel lettore) oppure impressi
    nell'immagine (sempre visibili, serve ricodificare). I contenitori senza tracce di sottotitoli li imprimono."""
    if burn or out_ext not in SUB_CODEC:
        if job is not None and not burn:
            add_note(job, f"sottotitoli impressi nel video: il formato {out_ext.upper()} non ha tracce di sottotitoli")
        flt = f"subtitles=filename='{subs}'"
        out = []
        for args in attempts:
            if "-c" in args and "copy" in args:  # la copia senza ricodifica non puo' disegnare i sottotitoli
                continue
            args = list(args)
            if "-vf" in args:
                args[args.index("-vf") + 1] += "," + flt
            else:
                args += ["-vf", flt]
            out.append(args)
        return out, base
    codec = "ass" if out_ext == "mkv" and subs.suffix.lower() in (".ass", ".ssa") else SUB_CODEC[out_ext]
    out = []
    for args in attempts:
        maps = [] if "-map" in args else ["-map", "0:v?", "-map", "0:a?"]
        out.append([*maps, *args, "-map", "1:0", "-c:s", codec])
    at = base.index("-i") + 2  # subito dopo il video: le opzioni che seguono valgono per il file d'uscita
    return out, [*base[:at], "-i", str(subs), *base[at:]]


async def email(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """EML/MSG -> HTML leggibile (poi PDF, Word...) oppure -> ZIP con gli allegati (vedi emailconv.py)."""
    out = wd / f"out.{out_ext}"
    script = Path(__file__).with_name("emailconv.py")
    try:
        await run(["python3", str(script), "zip" if out_ext == "zip" else "html", str(inp), str(out),
                   getattr(job, "lang", "it") or "it"], timeout=600, limit_memory=True)
    except ConvError as e:
        if "restituito 3" in str(e):
            raise ConvError("nessun allegato nell'email") from None
        if "restituito 4" in str(e):
            raise ConvError("email danneggiata o non leggibile") from None
        raise
    return out


async def subtitles(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    await run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(inp), str(out)], timeout=300)
    return out


# ------------------------------------------------------------------------------------------ testi, ebook
async def calibre(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"

    def on_line(line: str):
        m = re.match(r"\s*(\d+)%", line)
        if m:
            job.progress = int(m.group(1)) / 100

    await run(["ebook-convert", str(inp), str(out)], timeout=1800, on_line=on_line)
    return out


PANDOC_READ = {"md": "markdown", "rst": "rst", "org": "org", "tex": "latex", "html": "html", "ipynb": "ipynb",
               "textile": "textile", "docx": "docx", "odt": "odt", "epub": "epub", "dbk": "docbook",
               "wiki": "mediawiki", "opml": "opml", "t2t": "t2t", "typ": "typst", "csv": "csv", "tsv": "tsv"}
PANDOC_WRITE = {"md": "markdown", "html": "html", "docx": "docx", "odt": "odt", "rst": "rst", "tex": "latex",
                "txt": "plain", "epub": "epub", "ipynb": "ipynb", "adoc": "asciidoc", "typ": "typst",
                "dbk": "docbook5", "wiki": "mediawiki", "org": "org", "textile": "textile", "texi": "texinfo",
                "pptx": "pptx"}


# Pandoc scarica da solo le immagini remote (![](http://...)) quando crea DOCX, ODT o EPUB: da un file caricato
# si potrebbero far chiamare al server indirizzi della rete locale. Un proxy inesistente blocca ogni richiesta;
# Pandoc avvisa e mette il testo alternativo. Le pagine web passano da POST /api/fetch, con i suoi controlli.
NO_NETWORK = {k: "http://127.0.0.1:9" for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy")}
NO_NETWORK |= {"no_proxy": "", "NO_PROXY": ""}
PANDOC_BINARY = {"docx", "odt", "epub", "pptx", "html"}  # qui le immagini restano incorporate


async def pandoc(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    # Niente --sandbox: con il pandoc di Debian blocca anche i suoi modelli (docx/odt/epub).
    # Le risorse (immagini incluse) si cercano solo nella cartella del lavoro.
    if ext_of(inp.name) == "html" and out_ext not in PANDOC_BINARY:
        # articoli da una pagina web: nei formati di testo l'indirizzo dell'immagine, non i suoi dati
        from .webpage import restore_image_urls
        text = inp.read_text(encoding="utf-8", errors="replace")
        if "data-orig=" in text:
            inp = wd / "article.html"
            inp.write_text(restore_image_urls(text), encoding="utf-8")
    await run(["pandoc", "-s", f"--resource-path={inp.parent}", "-f", PANDOC_READ[ext_of(inp.name)],
               "-t", PANDOC_WRITE[out_ext], "-o", str(out), str(inp)], timeout=600, env=NO_NETWORK)
    return out


async def archive(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    tree = wd / "tree"
    tree.mkdir()
    await run(["bsdtar", "-xf", str(inp), "-C", str(tree)], timeout=3600)  # bsdtar rifiuta ../ e percorsi assoluti
    out = wd / f"out.{out_ext}"
    if out_ext == "7z":
        seven = shutil.which("7z") or shutil.which("7zz") or "7z"
        await run([seven, "a", "-t7z", "-mx=7", str(out), "."], cwd=tree, timeout=3600)
    else:
        await run(["bsdtar", "-a", "-cf", str(out), "-C", str(tree), "."], timeout=3600)
    return out


# ------------------------------------------------------------------------------------------------- dati
def load_data(path: Path, ext: str):
    import tomllib

    import yaml
    text = path.read_text(encoding="utf-8-sig")
    if ext == "json":
        return json.loads(text)
    if ext == "yaml":
        docs = [d for d in yaml.safe_load_all(text)]
        return docs[0] if len(docs) == 1 else docs
    if ext == "toml":
        return tomllib.loads(text)
    if ext in ("csv", "tsv"):
        sep = chr(csv_separator(text[:65536], ext))
        return list(csv.DictReader(io.StringIO(text), delimiter=sep))
    raise ConvError(f"formato di dati sconosciuto: {ext}")


def to_rows(data) -> tuple[list[str], list[dict]]:
    """Dati qualsiasi -> (colonne, righe) per un CSV. I valori annidati diventano testo JSON."""
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(data) == 1 and lists else [data]  # {"elementi": [...]} -> la lista
    if not isinstance(data, list):
        data = [data]
    rows, columns = [], {}
    for item in data:
        row = item if isinstance(item, dict) else {"valore": item}
        rows.append(row)
        columns.update(dict.fromkeys(map(str, row)))
    cell = lambda v: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v
    return list(columns), [{str(k): cell(v) for k, v in r.items()} for r in rows]


def dump_data(data, path: Path, ext: str) -> None:
    import yaml
    if ext == "json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    elif ext == "yaml":
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
                        encoding="utf-8")
    elif ext == "csv":
        columns, rows = to_rows(data)
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
    else:
        raise ConvError(f"non so scrivere {ext}")


def convert_data(inp: Path, out: Path, src: str, dst: str) -> None:
    try:
        data = load_data(inp, src)
    except ConvError:
        raise
    except Exception as e:  # noqa: BLE001 - JSON/YAML/TOML/CSV non validi
        raise ConvError(f"file {src.upper()} non valido: {e}") from None
    dump_data(data, out, dst)


async def data(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    await asyncio.to_thread(convert_data, inp, out, ext_of(inp.name), out_ext)
    return out


# -------------------------------------------------------------------------------------------------- font
FONT_SCRIPT = r"""
import sys
from fontTools.ttLib import TTFont
src, dst, target = sys.argv[1:]
font = TTFont(src)
cff = "CFF " in font or "CFF2" in font
if target == "ttf" and cff:
    sys.exit("il font ha contorni PostScript (CFF): convertilo in OTF")
if target == "otf" and not cff:
    sys.exit("il font ha contorni TrueType: convertilo in TTF")
font.flavor = target if target in ("woff", "woff2") else None
font.save(dst)
"""


async def font(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    await run(["python3", "-c", FONT_SCRIPT, str(inp), str(out), out_ext], timeout=300)
    return out


async def xournalpp(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.pdf"
    await run(["xvfb-run", "-a", "xournalpp", f"--create-pdf={out}", str(inp)], cwd=inp.parent, timeout=600)
    return out
