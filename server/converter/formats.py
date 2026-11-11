"""Formati conosciuti: estensioni, sinonimi e categorie."""
from __future__ import annotations

from pathlib import Path

ALIASES = {"jpeg": "jpg", "jfif": "jpg", "jpe": "jpg", "tif": "tiff", "htm": "html", "xhtml": "html",
           "markdown": "md", "latex": "tex", "tgz": "tar.gz", "tbz2": "tar.bz2", "tbz": "tar.bz2", "txz": "tar.xz",
           "tzst": "tar.zst", "aif": "aiff", "oga": "ogg", "heif": "heic", "mpeg": "mpg", "m2ts": "mts",
           "text": "txt", "ppsx": "pptx", "pps": "ppt", "dotx": "docx", "dot": "doc", "xlsm": "xlsx",
           "docm": "docx", "pptm": "pptx", "yml": "yaml", "j2k": "jp2", "jpf": "jp2", "asciidoc": "adoc",
           "texinfo": "texi", "docbook": "dbk", "mediawiki": "wiki"}
COMPOUND = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst")
_COMPOUND_ALIASES = ("tgz", "tbz2", "tbz", "txz", "tzst")

CATEGORIES = {  # categoria mostrata nella pagina, nell'ordine dei menu
    "Documento": ["pdf", "docx", "odt", "doc", "rtf", "txt", "html", "md", "tex", "rst", "adoc", "typ", "org",
                  "pages", "wpd", "wps", "fodt", "abw", "sxw", "lwp", "hwp", "ipynb", "textile", "dbk", "wiki",
                  "texi", "opml", "t2t", "xopp"],
    "Foglio di calcolo": ["xlsx", "ods", "xls", "csv", "tsv", "numbers", "fods", "xlsb", "sxc", "dif", "slk",
                          "dbf", "wk1"],
    "Presentazione": ["pptx", "odp", "ppt", "key", "fodp", "sxi"],
    "Disegno": ["svg", "eps", "ps", "vsd", "vsdx", "odg", "pub", "cdr", "wmf", "emf"],
    "Immagine": ["jpg", "png", "webp", "heic", "avif", "gif", "tiff", "bmp", "ico", "jp2", "qoi", "tga", "psd",
                 "ppm", "pbm", "pgm", "pnm", "pcx", "dds", "hdr", "xcf", "xpm", "apng",
                 "dng", "cr2", "cr3", "nef", "arw", "raf", "orf", "rw2"],
    "Audio": ["mp3", "m4a", "wav", "flac", "ogg", "opus", "aac", "aiff", "wma", "ac3", "mka", "amr", "dts", "ape",
              "wv", "caf", "au", "mp2", "tta"],
    "Video": ["mp4", "mkv", "mov", "webm", "avi", "wmv", "flv", "m4v", "3gp", "mts", "mpg", "ts", "ogv", "vob",
              "mxf", "asf", "rm", "rmvb", "f4v", "divx", "dv"],
    "Sottotitoli": ["srt", "vtt", "ass", "ssa"],
    "Ebook": ["epub", "mobi", "azw3", "azw", "fb2", "lit", "pdb", "htmlz", "txtz", "lrf", "cbz", "cbr", "cb7", "chm",
              "snb", "tcr", "pml"],
    "Dati": ["json", "yaml", "toml"],
    "Font": ["ttf", "otf", "woff", "woff2"],
    "Archivio": ["zip", "7z", "tar.gz", "tar.xz", "tar.bz2", "tar.zst", "tar", "rar", "iso", "cab", "cpio", "lha"],
}
CATEGORY_OF = {e: c for c, exts in CATEGORIES.items() for e in exts}
ORDER = {e: i for i, e in enumerate(e for exts in CATEGORIES.values() for e in exts)}


def category(ext: str) -> str:
    return CATEGORY_OF.get(ext, "Documento")


def normalize(ext: str) -> str:
    ext = ext.lower().strip().lstrip(".")
    return ALIASES.get(ext, ext)


def ext_of(name: str) -> str:
    """Estensione normalizzata: "Foto.JPEG" -> "jpg", "backup.tgz" -> "tar.gz"."""
    low = name.lower()
    for c in COMPOUND:
        if low.endswith("." + c):
            return c
    return normalize(low.rsplit(".", 1)[-1]) if "." in low else ""


def stem_of(name: str) -> str:
    """Nome senza percorso ed estensione: "a/b/backup.tar.gz" -> "backup"."""
    name = Path(name.replace("\\", "/")).name
    low = name.lower()
    for c in COMPOUND + _COMPOUND_ALIASES:
        if low.endswith("." + c):
            return name[: -len(c) - 1] or "file"
    return (name.rsplit(".", 1)[0] if "." in name else name) or "file"


def safe_filename(name: str | None, limit: int = 200) -> str:
    """Solo il nome del file, senza percorso, caratteri di controllo o lunghezze eccessive."""
    base = Path((name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    if base in ("", ".", ".."):
        return "file"
    if len(base) > limit:
        suffix = base[len(stem_of(base)):]  # estensione originale, anche doppia (.tar.gz)
        if not suffix or len(suffix) > 20:
            suffix = ""
        base = base[: limit - len(suffix)] + suffix
    return base
