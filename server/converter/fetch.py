"""Scarica un file da un indirizzo web, per convertirlo senza passare dal proprio computer.

Protezioni (il servizio di solito sta in una rete di casa o d'ufficio):
- solo http e https, al massimo 5 redirect, ognuno ricontrollato;
- l'host viene risolto una volta e la connessione va all'indirizzo controllato (niente "DNS rebinding");
- indirizzi privati, locali, di loopback e riservati rifiutati, salvo URL_ALLOW_PRIVATE=true;
- dimensione massima MAX_UPLOAD_GB (o il limite giornaliero della chiave), 30 secondi di timeout per lettura.
"""
from __future__ import annotations

import email.message
import http.client
import ipaddress
import mimetypes
import socket
import ssl
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from . import __version__

MAX_REDIRECTS = 5
TIMEOUT = 30
CHUNK = 1024 * 1024
# tipi MIME per cui mimetypes sceglie un'estensione scomoda o nessuna
MIME_EXT = {"image/jpeg": "jpg", "text/plain": "txt", "text/html": "html", "text/markdown": "md",
            "application/xhtml+xml": "html", "image/svg+xml": "svg", "audio/mpeg": "mp3", "image/heic": "heic",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
            "application/epub+zip": "epub", "application/x-yaml": "yaml", "application/json": "json",
            "video/quicktime": "mov", "audio/x-wav": "wav", "audio/wav": "wav", "audio/mp4": "m4a"}


class FetchError(Exception):
    """Il download non e' riuscito: ``status`` e' il codice HTTP da restituire, il messaggio va all'utente."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _check_ip(ip: str, allow_private: bool) -> None:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if allow_private:
        if addr.is_unspecified or addr.is_multicast:
            raise FetchError(400, "Indirizzo non ammesso")
        return
    if not addr.is_global or addr.is_multicast:
        raise FetchError(400, "Indirizzo della rete locale non ammesso (URL_ALLOW_PRIVATE)")


def resolve(host: str, port: int, allow_private: bool) -> str:
    """Primo indirizzo IP dell'host, dopo aver controllato che nessuno sia privato."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError(400, f"Host sconosciuto: {host}") from None
    ips = list(dict.fromkeys(i[4][0] for i in infos))
    for ip in ips:
        _check_ip(ip, allow_private)
    return ips[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Connessione HTTPS verso un IP gia' controllato, con il nome dell'host per il certificato."""

    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def check_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise FetchError(400, "Indirizzo mancante")
    if len(url) > 4000:
        raise FetchError(400, "Indirizzo troppo lungo")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise FetchError(400, "Serve un indirizzo http o https")
    if u.username or u.password:
        raise FetchError(400, "Indirizzi con nome utente e password non ammessi")
    return url


def filename_for(url: str, headers: http.client.HTTPMessage) -> tuple[str, str]:
    """Nome del file: Content-Disposition, poi l'ultima parte dell'indirizzo, con l'estensione dal Content-Type."""
    name = ""
    cd = headers.get("content-disposition")
    if cd:
        m = email.message.Message()
        m["content-disposition"] = cd
        name = m.get_filename() or ""
    if not name:
        name = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "download"
    mime = (headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = MIME_EXT.get(mime) or (mimetypes.guess_extension(mime) or "").lstrip(".")
    return name, ext


def download(url: str, dest: Path, max_bytes: int, allow_private: bool = False) -> tuple[str, str, int]:
    """Scarica ``url`` in ``dest``: (nome del file, estensione suggerita dal Content-Type, byte). Bloccante."""
    url = check_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        u = urlparse(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        ip = resolve(u.hostname, port, allow_private)
        cls = _PinnedHTTPS if u.scheme == "https" else _PinnedHTTP
        conn = cls(u.hostname, ip, port, TIMEOUT)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        try:
            conn.request("GET", path, headers={"User-Agent": f"UniversalConverter/{__version__}", "Accept": "*/*",
                                               "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("location")
                if not loc:
                    raise FetchError(502, f"Il sito ha risposto {resp.status} senza indirizzo")
                url = check_url(urljoin(url, loc))
                continue
            if resp.status != 200:
                raise FetchError(502, f"Il sito ha risposto {resp.status}")
            length = resp.getheader("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise FetchError(413, "File troppo grande")
            size = 0
            with dest.open("wb") as fh:
                while chunk := resp.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FetchError(413, "File troppo grande")
                    fh.write(chunk)
            if size == 0:
                raise FetchError(400, "File vuoto")
            name, ext = filename_for(url, resp.headers)
            return name, ext, size
        except (OSError, http.client.HTTPException) as e:
            if isinstance(e, ssl.SSLCertVerificationError):
                raise FetchError(502, "Certificato del sito non valido") from None
            raise FetchError(502, f"Download non riuscito: {e.__class__.__name__}") from None
        finally:
            conn.close()
    raise FetchError(502, "Troppi redirect")
