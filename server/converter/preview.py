"""Anteprima dei risultati, da mostrare nella pagina prima di scaricarli.

Tipi di anteprima (campo ``preview`` dello stato del lavoro):
  image  immagini che il browser sa mostrare (servite cosi' come sono), le altre immagini, SVG, PDF e documenti
         trasformati in un PNG (la prima pagina, per PDF e documenti), la prima immagine di uno ZIP di pagine
  audio  MP3, M4A, WAV, OGG, OPUS, FLAC cosi' come sono; gli altri formati in un MP3 dei primi 30 secondi
  video  MP4, WEBM, M4V, MOV cosi' come sono; gli altri formati in un MP4 a 480p dei primi 30 secondi
  text   i primi 64 KB dei formati di testo (anche HTML, mostrato come testo) e l'elenco dei file di un archivio
Le anteprime generate restano nella cartella del lavoro e spariscono con lui.
"""
from __future__ import annotations

import asyncio
import shutil
import tarfile
import types
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .formats import category, ext_of
from .runner import ConvError, run

if TYPE_CHECKING:
    from .graph import Graph
    from .jobs import Job

TEXT_LIMIT = 64 * 1024
CLIP_SECONDS = 30
WEB_IMAGES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif",
              "avif": "image/avif", "bmp": "image/bmp", "ico": "image/x-icon"}
WEB_AUDIO = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "wav": "audio/wav", "ogg": "audio/ogg",
             "opus": "audio/ogg", "flac": "audio/flac"}
WEB_VIDEO = {"mp4": "video/mp4", "webm": "video/webm", "m4v": "video/mp4", "mov": "video/mp4"}
TEXT = {"txt", "md", "csv", "tsv", "json", "yaml", "toml", "html", "xml", "srt", "vtt", "ass", "ssa", "rst", "tex",
        "org", "adoc", "typ", "wiki", "textile", "dbk", "opml", "ipynb", "texi", "svg"}
DOC_CATEGORIES = {"Documento", "Foglio di calcolo", "Presentazione", "Disegno"}
ARCHIVES = {"zip", "tar", "tar.gz", "tar.xz", "tar.bz2", "7z", "tar.zst"}


def _zip_first_image(path: Path) -> str:
    """Nome della prima immagine dentro uno ZIP (es. le pagine di un PDF), oppure ""."""
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if not n.endswith("/"))
    except (zipfile.BadZipFile, OSError):
        return ""
    return names[0] if names and ext_of(names[0]) in WEB_IMAGES | {"svg": ""} else ""


def kind(out_path: Path, out_name: str, graph: Graph) -> str:
    """Tipo di anteprima per un risultato ("" = nessuna)."""
    ext = ext_of(out_name)
    if ext in WEB_IMAGES or ext == "pdf" or (category(ext) == "Immagine" and ext not in ("ico",)):
        return "image"
    if ext in TEXT and ext != "svg":
        return "text"
    if ext == "svg":
        return "image"
    if ext in WEB_AUDIO or category(ext) == "Audio":
        return "audio"
    if ext in WEB_VIDEO or category(ext) == "Video":
        return "video"
    if ext == "zip" and _zip_first_image(out_path):
        return "image"
    if ext in ARCHIVES:
        return "text"
    if category(ext) in DOC_CATEGORIES and graph.plan(ext, "pdf"):
        return "image"
    return ""


class PreviewError(Exception):
    """Anteprima non disponibile per questo risultato."""


async def _first_page_png(pdf: Path, wd: Path) -> Path:
    await run(["pdftoppm", "-png", "-r", "80", "-f", "1", "-l", "1", "-singlefile", str(pdf), str(wd / "page")],
              timeout=120)
    return wd / "page.png"


async def _image_png(src: Path, wd: Path) -> Path:
    out = wd / "image.png"
    if ext_of(src.name) == "svg":
        await run(["rsvg-convert", "-w", "1200", "--keep-aspect-ratio", "-f", "png", "-o", str(out), str(src)],
                  timeout=120)
    else:
        await run(["magick", f"{src}[0]", "-auto-orient", "-resize", "1600x1600>", str(out)], timeout=300)
    return out


async def _text(src: Path, wd: Path, ext: str) -> Path:
    out = wd / "text.txt"
    if ext in ARCHIVES:
        names: list[str] = []
        try:
            if ext == "zip":
                with zipfile.ZipFile(src) as z:
                    names = [f"{i.filename}  ({i.file_size} B)" for i in z.infolist()[:2000]]
            elif ext.startswith("tar"):
                with tarfile.open(src) as t:
                    for i, m in enumerate(t):
                        if i >= 2000:
                            break
                        names.append(f"{m.name}  ({m.size} B)")
            else:
                listing = await run(["bsdtar", "-tf", str(src)], timeout=120)
                names = listing.splitlines()
        except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
            raise PreviewError(str(e)) from None
        out.write_text("\n".join(names) + "\n", encoding="utf-8")
        return out
    with src.open("rb") as fh:
        data = fh.read(TEXT_LIMIT)
    out.write_text(data.decode("utf-8", "replace"), encoding="utf-8")
    return out


async def _clip(src: Path, wd: Path, video: bool) -> Path:
    out = wd / ("clip.mp4" if video else "clip.mp3")
    args = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-vf", "scale=-2:'min(480,ih)'",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]
            if video else ["-vn", "-c:a", "libmp3lame", "-q:a", "5"])
    await run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-t", str(CLIP_SECONDS), "-i", str(src), *args, str(out)],
              timeout=600)
    return out


async def _document_png(job: Job, graph: Graph, wd: Path) -> Path:
    """Documento -> PDF con i convertitori del grafo, poi la prima pagina in PNG."""
    ext = ext_of(job.out_name)
    plan = graph.plan(ext, "pdf")
    if not plan or len(plan) > 2:
        raise PreviewError("anteprima non disponibile")
    cur = wd / f"input.{ext}"
    shutil.copy(job.out_path, cur)
    fake = types.SimpleNamespace(id=job.id, dir=wd, step="", progress=None, options={}, target="pdf")
    for i, edge in enumerate(plan, 1):
        step = wd / f"step{i}"
        step.mkdir()
        out = await edge.fn(fake, cur, edge.dst, step)
        cur = out.rename(step / f"input.{edge.dst}")
    return await _first_page_png(cur, wd)


async def build(job: Job, graph: Graph) -> tuple[Path, str]:
    """Crea (o riprende) il file d'anteprima: (percorso, tipo MIME). Solleva PreviewError."""
    assert job.out_path
    ext = ext_of(job.out_name)
    wd = job.dir / "preview"
    done = wd / "ready"
    if done.exists():
        path, mime = done.read_text().split("\n", 1)
        return Path(path), mime
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir()
    src, k = job.out_path, job.preview
    try:
        if k == "image" and ext in WEB_IMAGES:
            path, mime = src, WEB_IMAGES[ext]
        elif k == "image" and ext == "zip":
            name = _zip_first_image(src)
            inner = wd / ("first." + ext_of(name))
            with zipfile.ZipFile(src) as z, z.open(name) as fh, inner.open("wb") as o:
                shutil.copyfileobj(fh, o)
            if ext_of(name) in WEB_IMAGES:
                path, mime = inner, WEB_IMAGES[ext_of(name)]
            else:
                path, mime = await _image_png(inner, wd), "image/png"
        elif k == "image" and ext == "pdf":
            path, mime = await _first_page_png(src, wd), "image/png"
        elif k == "image" and (category(ext) == "Immagine" or ext == "svg"):
            local = wd / f"src.{ext}"  # estensione giusta per ImageMagick e rsvg
            local.symlink_to(src)
            path, mime = await _image_png(local, wd), "image/png"
        elif k == "image":
            path, mime = await _document_png(job, graph, wd), "image/png"
        elif k == "text":
            path, mime = await _text(src, wd, ext), "text/plain; charset=utf-8"
        elif k == "audio":
            path, mime = (src, WEB_AUDIO[ext]) if ext in WEB_AUDIO else (await _clip(src, wd, False), "audio/mpeg")
        elif k == "video":
            path, mime = (src, WEB_VIDEO[ext]) if ext in WEB_VIDEO else (await _clip(src, wd, True), "video/mp4")
        else:
            raise PreviewError("anteprima non disponibile")
    except ConvError as e:
        raise PreviewError(str(e)) from None
    if not path.exists() or path.stat().st_size == 0:
        raise PreviewError("anteprima non disponibile")
    done.write_text(f"{path}\n{mime}")
    return path, mime


_locks: dict[str, asyncio.Lock] = {}


async def get(job: Job, graph: Graph, sem: asyncio.Semaphore) -> tuple[Path, str]:
    """Una sola generazione alla volta per lavoro; ``sem`` limita le anteprime contemporanee."""
    lock = _locks.setdefault(job.id, asyncio.Lock())
    try:
        async with lock, sem:
            return await build(job, graph)
    finally:
        if not lock.locked():
            _locks.pop(job.id, None)
