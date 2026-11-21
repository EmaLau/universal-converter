"""Webhook: a fine lavoro il server chiama l'indirizzo indicato in ``callback_url`` (facoltativo).

Corpo: lo stato pubblico del lavoro in JSON (lo stesso di GET /api/jobs/{id}), intestazioni:
  X-Converter-Event      job.done | job.error
  X-Converter-Signature  sha256=<HMAC-SHA256 del corpo con WEBHOOK_SECRET> (solo se il segreto e' impostato)
Tre tentativi (subito, dopo 5 e dopo 30 secondi), 10 secondi di timeout, nessun redirect seguito.
Con WEBHOOK_HOSTS si limitano gli host ammessi (es. "n8n.lan, paperless"); vuota = qualsiasi host.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import __version__

RETRY_DELAYS = (0, 5, 30)
TIMEOUT = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # un redirect potrebbe portare altrove: non lo seguiamo
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def check_url(url: str, allowed_hosts: frozenset[str]) -> str:
    """Restituisce l'indirizzo pulito oppure solleva ValueError con un messaggio per l'utente."""
    url = (url or "").strip()
    if not url:
        return ""
    if len(url) > 2000:
        raise ValueError("callback_url troppo lungo")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("callback_url deve essere un indirizzo http o https")
    if allowed_hosts and u.hostname.lower() not in allowed_hosts:
        raise ValueError(f"callback_url: host non ammesso ({u.hostname})")
    return url


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with _OPENER.open(req, timeout=TIMEOUT) as r:
        return r.status


async def deliver(url: str, payload: dict, secret: str = "", delays: tuple[int, ...] = RETRY_DELAYS) -> str:
    """Manda il webhook; restituisce "ok" oppure l'ultimo errore (non solleva mai)."""
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "User-Agent": f"UniversalConverter/{__version__}",
               "X-Converter-Event": f"job.{payload.get('state')}"}
    if secret:
        headers["X-Converter-Signature"] = signature(secret, body)
    last = ""
    for delay in delays:
        if delay:
            await asyncio.sleep(delay)
        try:
            status = await asyncio.to_thread(_post, url, body, headers)
            if 200 <= status < 300:
                return "ok"
            last = f"HTTP {status}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if 400 <= e.code < 500 and e.code not in (408, 429):  # errore del ricevente: inutile riprovare
                break
        except (OSError, ValueError) as e:
            last = str(e)[:200]
    return last or "errore"
