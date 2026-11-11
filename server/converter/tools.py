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


async def libreoffice(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    profile = job.dir / "lo-profile"  # profilo separato per lavoro: piu' istanze in parallelo
    cmd = ["soffice", f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nolockcheck"]
    src = ext_of(inp.name)
    if src in ("csv", "tsv"):
        with inp.open("rb") as fh:
            sample = fh.read(65536).decode("utf-8", "replace")
        cmd.append(f"--infilter=CSV:{csv_separator(sample, src)},34,76,1")
    lo_filter, produced = LO_FILTERS_BY_KIND.get((category(src), out_ext), (LO_FILTERS.get(out_ext), out_ext))
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
    if not out.exists():
        raise ConvError("LibreOffice non ha prodotto il file (formato non riconosciuto o file danneggiato)")
    return out


# ------------------------------------------------------------------------------------------------- PDF
async def pdf_to_docx(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.docx"
    code = ("import sys,logging;logging.disable(logging.WARNING);from pdf2docx import Converter;"
            "c=Converter(sys.argv[1]);c.convert(sys.argv[2]);c.close()")
    await run(["python3", "-c", code, str(inp), str(out)], timeout=1800)
    return out


async def pdf_to_text(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / "out.txt"
    await run(["pdftotext", "-layout", "-enc", "UTF-8", str(inp), str(out)], timeout=600)
    return out


async def pdf_to_images(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    """Una immagine per pagina; con piu' pagine il risultato e' uno zip."""
    fmt = ["-png"] if out_ext == "png" else ["-jpeg", "-jpegopt", "quality=90"]
    pages = wd / "pages"
    pages.mkdir()
    await run(["pdftoppm", "-r", "150", *fmt, str(inp), str(pages / "pagina")], timeout=1800)
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
    out = wd / f"out.{out_ext}"
    src = str(inp) if out_ext in ("gif", "webp", "tiff") else f"{inp}[0]"  # animazioni e pagine multiple
    args = ["magick", src, "-auto-orient"]
    if out_ext in ("jpg", "bmp"):  # formati senza trasparenza: sfondo bianco invece di nero
        args += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
    if out_ext == "ico":
        args += ["-resize", "256x256>", "-define", "icon:auto-resize=256,128,64,48,32,16"]
    if out_ext in ("jpg", "webp", "heic", "avif", "jxl"):
        args += ["-quality", "90"]
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


def ffmpeg_attempts(out_ext: str, vcodec: str, acodec: str) -> list[list[str]]:
    """Argomenti da provare in ordine: prima la copia senza ricodifica, quando il contenitore lo permette."""
    if out_ext in AUDIO_ARGS:
        return [["-vn", *AUDIO_ARGS[out_ext]]]
    if out_ext == "gif":
        return [["-t", str(GIF_SECONDS), "-an", "-filter_complex", GIF_FILTER, "-loop", "0"]]
    attempts = [VIDEO_ARGS[out_ext]]
    hevc_ok = out_ext in ("mp4", "mov", "m4v", "ts")
    if out_ext in COPY_H264 and (vcodec == "h264" or (vcodec == "hevc" and hevc_ok)) and acodec in ("aac", "mp3", ""):
        attempts.insert(0, ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", *COPY_H264[out_ext]])
    elif out_ext == "mkv":  # mkv accetta quasi tutti i codec
        attempts.insert(0, ["-map", "0", "-c", "copy"])
    return attempts


async def ffmpeg(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    duration = await ffprobe_duration(inp)
    if out_ext == "gif":
        duration = min(duration, GIF_SECONDS)
    vcodec, acodec = ("", "") if out_ext in AUDIO_ARGS or out_ext == "gif" else await ffprobe_codecs(inp)
    base = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(inp), "-map_metadata", "0"]

    def on_line(line: str):
        m = re.match(r"out_time_us=(\d+)", line)
        if m and duration > 0:
            job.progress = min(0.99, int(m.group(1)) / 1e6 / duration)

    err: ConvError | None = None
    for args in ffmpeg_attempts(out_ext, vcodec, acodec):
        try:
            await run(base + args + ["-progress", "pipe:1", "-nostats", str(out)], timeout=4 * 3600,
                      on_line=on_line)
            return out
        except ConvError as e:
            err = e
            out.unlink(missing_ok=True)
    raise err or ConvError("ffmpeg non riuscito")


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


async def pandoc(job: Job, inp: Path, out_ext: str, wd: Path) -> Path:
    out = wd / f"out.{out_ext}"
    # Niente --sandbox: con il pandoc di Debian blocca anche i suoi modelli (docx/odt/epub).
    # Le risorse (immagini incluse) si cercano solo nella cartella del lavoro.
    await run(["pandoc", "-s", f"--resource-path={inp.parent}", "-f", PANDOC_READ[ext_of(inp.name)],
               "-t", PANDOC_WRITE[out_ext], "-o", str(out), str(inp)], timeout=600)
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
