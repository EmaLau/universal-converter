"""Pagina web -> articolo: il contenuto principale di una pagina, senza menu, pubblicita' e script.

Usato da ``POST /api/fetch`` con ``article=true`` (la pagina web lo chiede sempre): l'HTML scaricato diventa un
documento pulito con titolo, indirizzo d'origine e immagini incorporate (``data:``), cosi' PDF, Word ed EPUB
hanno le immagini senza che i convertitori debbano andare in rete. Per i formati di testo (Markdown, reStructuredText…)
``restore_image_urls`` rimette gli indirizzi originali, conservati in ``data-orig``.

Le immagini si scaricano con gli stessi controlli di fetch.py (niente rete locale, salvo URL_ALLOW_PRIVATE):
al massimo MAX_IMAGES, ciascuna fino a MAX_IMAGE_BYTES, in tutto fino a MAX_TOTAL_BYTES.
"""
from __future__ import annotations

import base64
import html as htmllib
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from . import fetch

MAX_IMAGES = 40
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024
WORKERS = 6
EMBED = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif"}  # gli altri (webp, avif…) diventano PNG
KEEP_ATTRS = {"href", "src", "alt", "title", "colspan", "rowspan", "data-orig", "start", "type"}
NOISE_CLASSES = ("mw-editsection", "noprint", "navbox", "share", "social", "sharing", "newsletter", "related",
                 "advertisement", "ad", "ads", "cookie", "breadcrumb", "skip-link", "screen-reader-text")
LAZY = ("data-src", "data-original", "data-lazy-src", "data-url", "data-hi-res-src")


def decode(raw: bytes) -> str:
    m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", raw[:4096], re.I)
    for enc in ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8", "cp1252"]:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def image_url(img, base: str) -> str:
    """Indirizzo vero di un'immagine: anche quelle caricate "pigramente" (data-src, srcset)."""
    src = (img.get("src") or "").strip()
    for attr in LAZY:
        if img.get(attr) and (not src or src.startswith("data:")):
            src = img.get(attr).strip()
    if (not src or src.startswith("data:")) and img.get("srcset"):
        src = img.get("srcset").split(",")[-1].strip().split(" ")[0]  # di solito l'ultima e' la piu' grande
    if not src or src.startswith("data:"):
        return ""
    return urljoin(base, src)


def fetch_image(url: str, allow_private: bool) -> tuple[str, bytes] | None:
    """(tipo MIME, byte) di un'immagine pronta da incorporare, oppure None se non si scarica o non e' un'immagine."""
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "img"
        try:
            _, ext, _ = fetch.download(url, dest, MAX_IMAGE_BYTES, allow_private)
        except fetch.FetchError:
            return None
        head = dest.read_bytes()[:16]
        kind = ("png" if head.startswith(b"\x89PNG") else "jpg" if head.startswith(b"\xff\xd8")
                else "gif" if head[:4] == b"GIF8" else ext)
        if kind in EMBED:
            return EMBED[kind], dest.read_bytes()
        if kind not in ("webp", "avif", "heic", "bmp", "tiff", "svg", "ico"):
            return None
        png = Path(d) / "img.png"
        try:  # niente rete per ImageMagick: legge solo il file scaricato
            subprocess.run(["magick", f"{kind}:{dest}[0]", "-resize", "2400x2400>", str(png)], check=True,
                           timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return "image/png", png.read_bytes()


def best_title(title: str, body) -> str:
    """"Titolo - Nome del sito" -> "Titolo", se una parte coincide con un titolo dell'articolo."""
    parts = [p.strip() for p in re.split(r"\s+[-|–—·»:]\s+", title) if p.strip()]
    if len(parts) < 2:
        return title
    heads = {" ".join(h.text_content().split()) for h in body.xpath("//h1|//h2|//h3")}
    return next((p for p in parts if p in heads), title)


def article(raw: bytes, url: str, allow_private: bool = False) -> tuple[str, str]:
    """(titolo, HTML pulito e autonomo) dall'HTML di una pagina."""
    import lxml.html
    from readability import Document

    text = decode(raw)
    doc = Document(text, url=url)
    title = (doc.short_title() or doc.title() or "").strip() or "Pagina web"
    body = lxml.html.fragment_fromstring(doc.summary(html_partial=True), create_parent="div")
    title = best_title(title, body)
    first = next(iter(body.xpath("//h1|//h2")), None)
    if first is not None and " ".join(first.text_content().split()) == title:
        first.drop_tree()  # il titolo c'e' gia' in cima
    body.make_links_absolute(url, resolve_base_href=False)
    for bad in body.xpath("//script|//style|//noscript|//iframe|//form|//object|//embed|//button|//svg"):
        bad.drop_tree()
    for bad in body.xpath(" | ".join(f"//*[contains(concat(' ', normalize-space(@class), ' '), ' {c} ')]"
                                     for c in NOISE_CLASSES)):
        bad.drop_tree()  # "modifica", barre di condivisione, box di navigazione
    imgs = body.xpath("//img")
    urls = [image_url(i, url) for i in imgs]
    wanted = list(dict.fromkeys(u for u in urls if u))[:MAX_IMAGES]
    with ThreadPoolExecutor(WORKERS) as pool:
        got = dict(zip(wanted, pool.map(lambda u: fetch_image(u, allow_private), wanted)))
    total = 0
    for img, u in zip(imgs, urls):
        data = got.get(u)
        if not data or total + len(data[1]) > MAX_TOTAL_BYTES:
            img.drop_tree()
            continue
        total += len(data[1])
        for attr in list(img.attrib):
            if attr not in ("alt", "title", "width", "height"):
                del img.attrib[attr]
        img.set("src", f"data:{data[0]};base64,{base64.b64encode(data[1]).decode('ascii')}")
        img.set("data-orig", u)
    for el in body.iter():  # solo gli attributi utili: niente stili, classi e gestori di eventi della pagina
        if not isinstance(el.tag, str):
            continue
        for attr in [a for a in el.attrib if a not in KEEP_ATTRS]:
            del el.attrib[attr]
    for a in body.xpath("//a[img and not(normalize-space(string()))]"):
        a.drop_tag()  # link che contiene solo un'immagine (di solito verso la pagina del file): resta l'immagine
    for el in body.xpath("//div|//section|//span|//font|//center|//article|//main|//header"):
        if el.getparent() is not None:  # il contenitore radice resta
            el.drop_tag()  # contenitori senza significato: nel Markdown diventerebbero blocchi ::: e <div>
    # il contenuto senza il contenitore radice (altrimenti nel Markdown resta un <div>)
    content = htmllib.escape(body.text or "") + "".join(lxml.html.tostring(c, encoding="unicode") for c in body)
    t, u = htmllib.escape(title), htmllib.escape(url)
    page = (f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{t}</title></head>\n<body>\n'
            f'<h1>{t}</h1>\n<p><a href="{u}">{u}</a></p>\n{content}\n</body></html>\n')
    return title, page


IMG_DATA = re.compile(r"<img\b[^>]*>", re.I)


def restore_image_urls(html: str) -> str:
    """Per i formati di testo: al posto dei dati incorporati, l'indirizzo originale dell'immagine."""
    def fix(m: re.Match) -> str:
        tag = m.group(0)
        orig = re.search(r'data-orig="([^"]*)"', tag)
        if not orig or 'src="data:' not in tag:
            return tag
        tag = re.sub(r'\s*data-orig="[^"]*"', "", tag)
        return re.sub(r'src="data:[^"]*"', f'src="{orig.group(1)}"', tag)
    return IMG_DATA.sub(fix, html)
