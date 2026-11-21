"""Email (EML e MSG di Outlook) in HTML leggibile, o i loro allegati in uno ZIP.

L'HTML ha oggetto, mittente, destinatari, data, elenco degli allegati e il testo del messaggio, con le immagini
incorporate (cid:) al loro posto; da li' il convertitore arriva a PDF, Word, EPUB, Markdown. Le immagini esterne
NON vengono caricate (sono spesso pixel che segnalano la lettura): restano come testo alternativo. Script, stili
esterni, moduli e iframe vengono tolti. Gira in un processo separato, con tempo e memoria limitati:

    python3 emailconv.py html|zip in.eml|in.msg out [it|en]

Esce con codice 3 se si chiede lo ZIP e non ci sono allegati.
"""
from __future__ import annotations

import base64
import email
import email.policy
import html as htmllib
import re
import sys
import zipfile
from dataclasses import dataclass, field
from email.utils import format_datetime, parsedate_to_datetime

NO_ATTACHMENTS = 3
LABELS = {"it": {"from": "Da", "to": "A", "cc": "Cc", "date": "Data", "att": "Allegati", "ext": "immagine esterna"},
          "en": {"from": "From", "to": "To", "cc": "Cc", "date": "Date", "att": "Attachments", "ext": "external image"}}


@dataclass
class Part:
    name: str
    data: bytes
    mime: str = "application/octet-stream"
    cid: str = ""
    inline: bool = False


@dataclass
class Mail:
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    date: str = ""
    html: str = ""
    text: str = ""
    parts: list[Part] = field(default_factory=list)


def read_eml(path: str) -> Mail:
    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=email.policy.default)
    m = Mail(subject=str(msg.get("subject", "") or ""), sender=str(msg.get("from", "") or ""),
             to=str(msg.get("to", "") or ""), cc=str(msg.get("cc", "") or ""))
    try:
        m.date = format_datetime(parsedate_to_datetime(msg["date"])) if msg.get("date") else ""
    except (TypeError, ValueError):
        m.date = str(msg.get("date", ""))
    body = msg.get_body(preferencelist=("html", "plain"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            m.html = content
        else:
            m.text = content
        if not m.text:
            plain = msg.get_body(preferencelist=("plain",))
            m.text = plain.get_content() if plain is not None and plain is not body else ""
    for part in msg.walk():
        if part.is_multipart() or part is body:
            continue
        disp = part.get_content_disposition()
        cid = (part.get("content-id") or "").strip("<> ")
        if disp is None and not cid and part.get_content_maintype() == "text":
            continue  # parti alternative del testo
        data = part.get_payload(decode=True) or b""
        name = part.get_filename() or (cid or "allegato")
        m.parts.append(Part(name=name, data=data, mime=part.get_content_type(), cid=cid,
                            inline=disp == "inline" or (bool(cid) and disp != "attachment")))
    return m


def read_msg(path: str) -> Mail:
    import extract_msg

    msg = extract_msg.Message(path)
    try:
        html = msg.htmlBody or b""
        m = Mail(subject=msg.subject or "", sender=msg.sender or "", to=msg.to or "", cc=msg.cc or "",
                 date=str(msg.date or ""), html=html.decode("utf-8", "replace") if isinstance(html, bytes) else html,
                 text=msg.body or "")
        for a in msg.attachments:
            data = getattr(a, "data", None)
            if not isinstance(data, bytes):
                continue  # messaggi allegati e altri oggetti: non sono file
            name = a.longFilename or a.shortFilename or getattr(a, "name", "") or "allegato"
            cid = (getattr(a, "cid", "") or "").strip("<> ")
            m.parts.append(Part(name=name, data=data, mime=getattr(a, "mimetype", "") or "application/octet-stream",
                                cid=cid, inline=bool(cid) and bool(getattr(a, "hidden", False) or cid in m.html)))
        return m
    finally:
        msg.close()


def clean_html(raw: str, parts: list[Part], ext_label: str) -> str:
    """HTML del messaggio senza script ne' risorse esterne; immagini cid: incorporate."""
    import lxml.html

    try:
        root = lxml.html.fromstring(raw or "<p></p>")
    except Exception:  # noqa: BLE001 - HTML illeggibile: meglio il testo semplice
        return ""
    body = root.find(".//body")
    body = body if body is not None else root
    for bad in body.xpath("//script|//style|//link|//meta|//iframe|//frame|//object|//embed|//form|//base|//svg"):
        bad.drop_tree()
    by_cid = {p.cid: p for p in parts if p.cid}
    for img in body.xpath("//img"):
        src = (img.get("src") or "").strip()
        part = by_cid.get(src[4:].strip("<> ")) if src.lower().startswith("cid:") else None
        if part and part.mime.startswith("image/"):
            img.set("src", f"data:{part.mime};base64,{base64.b64encode(part.data).decode('ascii')}")
        elif src.lower().startswith("data:image/"):
            pass
        else:  # immagine esterna (o mancante): non si scarica
            alt = img.get("alt") or ""
            span = lxml.html.fromstring(f"<span>[{htmllib.escape(ext_label)}{': ' + htmllib.escape(alt) if alt else ''}]</span>")
            span.tail = img.tail
            img.getparent().replace(img, span)
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            v = el.attrib[attr]
            if attr.startswith("on") or attr in ("background", "srcset") or (
                    attr in ("href", "src") and re.match(r"\s*(javascript|vbscript):", v, re.I)):
                del el.attrib[attr]
            elif attr == "style" and re.search(r"url\s*\(|expression\s*\(", v, re.I):
                del el.attrib[attr]  # sfondi e risorse esterne negli stili
    inner = (htmllib.escape(body.text or "") if body.text else "") + "".join(
        lxml.html.tostring(c, encoding="unicode") for c in body)
    return inner


def text_to_html(text: str) -> str:
    paras = re.split(r"\n\s*\n", text.strip())
    return "\n".join("<p>" + htmllib.escape(p).replace("\n", "<br>\n") + "</p>" for p in paras if p.strip())


def size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024**2 else f"{n / 1024**2:.1f} MB"


def to_html(m: Mail, lang: str = "it") -> str:
    L = LABELS.get(lang, LABELS["it"])
    attachments = [p for p in m.parts if not p.inline]
    rows = [(L["from"], m.sender), (L["to"], m.to), (L["cc"], m.cc), (L["date"], m.date)]
    if attachments:
        rows.append((L["att"], ", ".join(f"{p.name} ({size(len(p.data))})" for p in attachments)))
    head = "\n".join(f"<tr><th>{htmllib.escape(k)}</th><td>{htmllib.escape(v)}</td></tr>" for k, v in rows if v)
    body = clean_html(m.html, m.parts, L["ext"]) if m.html else ""
    if not body.strip():
        body = text_to_html(m.text)
    title = htmllib.escape(m.subject or "Email")
    return (f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{title}</title></head>\n<body>\n'
            f"<h1>{title}</h1>\n<table>\n{head}\n</table>\n<hr>\n{body}\n</body></html>\n")


def safe_name(name: str) -> str:
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", name).strip(" .") or "allegato"
    return name[:150]


def to_zip(m: Mail, out: str) -> int:
    files = [p for p in m.parts if not p.inline]
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            name, n = safe_name(p.name), 1
            stem, dot, ext = name.rpartition(".")
            while name.lower() in used:
                n += 1
                name = f"{stem} ({n}).{ext}" if dot else f"{safe_name(p.name)} ({n})"
            used.add(name.lower())
            z.writestr(name, p.data)
    return len(files)


def main(argv: list[str]) -> int:
    kind, src, out = argv[:3]
    lang = argv[3] if len(argv) > 3 else "it"
    try:
        m = read_msg(src) if src.lower().endswith(".msg") else read_eml(src)
    except Exception as e:  # noqa: BLE001 - file danneggiato: un messaggio, non la traccia di Python
        print(f"email non leggibile: {e.__class__.__name__}", file=sys.stderr)
        return 4
    if kind == "zip":
        if not any(not p.inline for p in m.parts) or to_zip(m, out) == 0:
            print("nessun allegato nell'email", file=sys.stderr)
            return NO_ATTACHMENTS
        return 0
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(to_html(m, lang))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
