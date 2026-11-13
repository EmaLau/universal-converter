"""Applicazione web: pagina su / e API JSON su /api.

API (intestazione facoltativa "apikey"; obbligatoria fuori dalla pagina web se la chiave e' obbligatoria)
  GET    /healthz                     stato del servizio
  GET    /api/formats                 {"inputs": {ext: [target...]}, "categories": {...}, "tools": [...]}
  GET    /api/plan/{src}/{dst}        passaggi previsti per una conversione
  POST   /api/jobs                    multipart: file, target, [meta]  -> 201 + stato del lavoro
  GET    /api/jobs/{id}               stato: queued | running | done | error
  GET    /api/jobs/{id}/download      risultato
  DELETE /api/jobs/{id}               cancella subito i file del lavoro
  GET    /docs                        documentazione
  GET    /apidocs                     documentazione interattiva dell'API
  GET    /admin                       chiavi API (apikeys.py)

Avvio: uvicorn --factory converter.app:create_app
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, Form, Request, Security, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__, apikeys
from .config import Settings
from .graph import Graph, default_graph
from .jobs import JobError, JobManager
from .runner import set_file_size_limit

STATIC = Path(__file__).parent / "static"
XRW = "converter"  # valore di X-Requested-With mandato dalla pagina admin

API_DOC = """Convertitore di file self-hosted: si carica un file, si controlla lo stato del lavoro, si scarica il risultato.

**Chiavi API.** Gli script mandano la chiave nell'intestazione `apikey` (si crea nella pagina `/admin`).
Ogni chiave ha dei permessi: `formats` (formati e piani), `convert` (avviare conversioni),
`jobs` (stato, download e cancellazione). La pagina web non ha bisogno della chiave.
Se nella pagina `/admin` la chiave è obbligatoria, le chiamate senza chiave vengono rifiutate (401).

Gli errori rispondono con JSON `{"detail": "..."}` e un codice HTTP.

Esempio: `curl -H "apikey: uconv_..." -F file=@relazione.docx -F target=pdf http://host:8080/api/jobs`"""


@lru_cache(maxsize=None)
def page(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _inline_hashes(*pages: str) -> str:
    """Hash degli script scritti dentro le pagine, per permetterli nella Content-Security-Policy."""
    out = []
    for name in pages:
        if (STATIC / name).exists():
            for body in re.findall(r"<script>(.*?)</script>", page(name), re.S):
                out.append("'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'")
    return " ".join(out)


# la documentazione Swagger carica i suoi file da jsDelivr e ha uno script nella pagina
CSP_DOCS = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def cross_site(request: Request) -> bool:
    """Vero per le richieste che modificano qualcosa inviate dal browser da una pagina di un altro sito."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin == "null"
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    return urlparse(origin).netloc not in hosts


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def create_app(settings: Settings | None = None, graph: Graph | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    graph = graph or default_graph(settings.disabled)
    manager = JobManager(settings, graph)
    keys = apikeys.KeyStore(settings.keys_dir, settings.admin_password, settings.require_key, settings.admin_login)
    set_file_size_limit(settings.max_output_bytes)
    csp_page = ("default-src 'self'; script-src 'self' " + _inline_hashes("index.html", "admin.html", "docs.html") +
                "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()
        yield
        await manager.stop()
        keys.flush()  # salva l'"ultimo uso" delle chiavi rimasto in memoria

    app = FastAPI(title="Universal Converter", version=__version__, description=API_DOC, lifespan=lifespan,
                  docs_url="/apidocs", redoc_url=None, openapi_url="/apidocs/openapi.json")
    app.state.manager = manager
    app.state.keys = keys
    api = {"dependencies": [Security(apikeys.header_scheme)], "tags": ["Conversioni"]}

    def security_headers(request: Request, resp):
        h = resp.headers
        h["Content-Security-Policy"] = CSP_DOCS if request.url.path == "/apidocs" else csp_page
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp

    @app.exception_handler(JobError)
    async def job_error(request: Request, exc: JobError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Richieste da altri siti, chiave e permessi (prima di ricevere il file), intestazioni di sicurezza."""
        try:
            if cross_site(request):
                raise JobError(403, "Richiesta inviata da un altro sito")
            perm = apikeys.permission_for(request.method, request.url.path)
            if perm:
                key = request.headers.get("apikey")
                if key:
                    keys.check_key(key, perm)
                elif keys.require_key and not keys.verify("session", request.cookies.get(apikeys.SESSION_COOKIE)):
                    raise JobError(401, "Serve una chiave API nell'intestazione 'apikey'")
        except JobError as e:
            return security_headers(request, JSONResponse({"detail": str(e)}, status_code=e.status))
        return security_headers(request, await call_next(request))

    # ------------------------------------------------------------ pagine

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        resp = HTMLResponse(page("index.html"), headers={"Cache-Control": "no-cache"})
        resp.set_cookie(apikeys.SESSION_COOKIE, keys.sign("session", apikeys.SESSION_TTL),
                        max_age=apikeys.SESSION_TTL, httponly=True, samesite="strict")
        return resp

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    async def docs():
        doc = STATIC / "docs.html"  # generata da docs/documentazione.md durante la build dell'immagine
        if not doc.exists():
            raise JobError(404, "Documentazione non generata: vedi docs/documentazione.md")
        return FileResponse(doc, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/healthz", tags=["Servizio"])
    async def healthz():
        """Stato del servizio: non richiede la chiave."""
        return {"ok": True, "version": __version__, **manager.stats()}

    # ------------------------------------------------------------ API

    @app.get("/api/formats", **api)
    async def formats():
        """Formati e combinazioni supportate. Permesso: `formats`."""
        return graph.payload() | {"retain_hours": settings.retain_hours,
                                  "max_upload_bytes": settings.max_upload_bytes}

    @app.get("/api/plan/{src}/{dst}", **api)
    async def plan(src: str, dst: str):
        """Passaggi previsti per una conversione. Permesso: `formats`."""
        steps = graph.plan(src, dst)
        if not steps:
            raise JobError(404, "Conversione non supportata")
        return [{"tool": e.tool, "from": e.src, "to": e.dst} for e in steps]

    @app.post("/api/jobs", status_code=201, **api)
    async def create_job(file: UploadFile = File(...), target: str = Form(...), meta: str = Form("")):
        """Crea un lavoro caricando un file e indicando il formato di destinazione. Permesso: `convert`."""
        job = await manager.create(file, file.filename, target, meta)
        return manager.public(job)

    @app.get("/api/jobs/{job_id}", **api)
    async def job_status(job_id: str):
        """Stato del lavoro: queued, running, done o error. Permesso: `jobs`."""
        return manager.public(manager.get(job_id))

    @app.get("/api/jobs/{job_id}/download", **api)
    async def job_download(job_id: str):
        """Scarica il risultato. Permesso: `jobs`."""
        job = manager.get(job_id)
        if job.state != "done" or not job.out_path:
            raise JobError(409, "Non ancora pronto")
        return FileResponse(job.out_path, filename=job.out_name, media_type="application/octet-stream")

    @app.delete("/api/jobs/{job_id}", **api)
    async def job_delete(job_id: str):
        """Cancella subito il lavoro e i suoi file. Permesso: `jobs`."""
        manager.drop(manager.get(job_id))
        return {"ok": True}

    # ------------------------------------------------------------ area admin (chiavi API)

    def admin_only(request: Request, write: bool = False):
        if not keys.admin_enabled:
            raise JobError(404, "Area admin disattivata: imposta CONVERTER_ADMIN_PASSWORD")
        if not keys.is_admin(request.cookies.get(apikeys.ADMIN_COOKIE)):
            raise JobError(401, "Accedi con la password admin")
        # contro le richieste inviate da pagine di altri siti
        if write and request.headers.get("x-requested-with") != XRW:
            raise JobError(403, "Richiesta non valida")

    def admin_cookie(resp):
        resp.set_cookie(apikeys.ADMIN_COOKIE, keys.sign("admin", apikeys.ADMIN_TTL), max_age=apikeys.ADMIN_TTL,
                        httponly=True, samesite="strict", path="/admin")
        return resp

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def admin_page():
        return HTMLResponse(page("admin.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/admin/api/state", include_in_schema=False)
    async def admin_state(request: Request):
        return {"enabled": keys.admin_enabled, "logged": keys.is_admin(request.cookies.get(apikeys.ADMIN_COOKIE)),
                "admin_login": keys.admin_login, "has_password": bool(keys.admin_password),
                "require_key": keys.require_key, "permissions": apikeys.PERMISSIONS}

    @app.post("/admin/api/login", include_in_schema=False)
    async def admin_login(request: Request, password: str = Body(..., embed=True)):
        if not keys.admin_password:
            raise JobError(404, "Nessuna password admin impostata")
        if request.headers.get("x-requested-with") != XRW:
            raise JobError(403, "Richiesta non valida")
        if not keys.login(client_ip(request), password):
            await asyncio.sleep(1)
            raise JobError(401, "Password sbagliata")
        return admin_cookie(JSONResponse({"ok": True}))

    @app.post("/admin/api/logout", include_in_schema=False)
    async def admin_logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(apikeys.ADMIN_COOKIE, path="/admin")
        return resp

    @app.put("/admin/api/settings", include_in_schema=False)
    async def admin_settings(request: Request, require_key: bool | None = Body(None),
                             admin_login: bool | None = Body(None)):
        admin_only(request, write=True)
        keys.update_settings(require_key, admin_login)
        resp = JSONResponse({"require_key": keys.require_key, "admin_login": keys.admin_login})
        return admin_cookie(resp) if admin_login else resp  # chi riattiva la password resta dentro

    @app.get("/admin/api/keys", include_in_schema=False)
    async def keys_list(request: Request):
        admin_only(request)
        return {"keys": keys.list()}

    @app.post("/admin/api/keys", include_in_schema=False)
    async def keys_create(request: Request, name: str = Body(...), perms: list[str] = Body(...)):
        admin_only(request, write=True)
        key, rec = keys.create(name, perms)
        return {"key": key, **rec}

    @app.put("/admin/api/keys/{kid}", include_in_schema=False)
    async def keys_update(request: Request, kid: str, name: str | None = Body(None),
                          perms: list[str] | None = Body(None)):
        admin_only(request, write=True)
        return keys.update(kid, name, perms)

    @app.delete("/admin/api/keys/{kid}", include_in_schema=False)
    async def keys_delete(request: Request, kid: str):
        admin_only(request, write=True)
        keys.delete(kid)
        return {"ok": True}

    return app
