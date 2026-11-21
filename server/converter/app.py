"""Applicazione web: pagina su / e API JSON su /api.

API (intestazione facoltativa "apikey"; obbligatoria fuori dalla pagina web se la chiave e' obbligatoria)
  GET    /healthz                     stato del servizio
  GET    /api/formats                 {"inputs": {ext: [target...]}, "categories": {...}, "tools": [...]}
  GET    /api/plan/{src}/{dst}        passaggi previsti per una conversione
  POST   /api/jobs                    multipart: file, target, [meta]  -> 201 + stato del lavoro
  GET    /api/pdf                     strumenti PDF disponibili e loro opzioni
  POST   /api/pdf/{tool}              multipart: files (uno o piu'), opzioni, [meta] -> 201 + stato del lavoro
  GET    /api/jobs/{id}               stato: queued | running | done | error
  GET    /api/jobs/{id}/download      risultato
  DELETE /api/jobs/{id}               cancella subito i file del lavoro
  GET    /docs                        documentazione (?lang=it|en)
  GET    /apidocs                     documentazione interattiva dell'API
  GET    /admin                       chiavi API (apikeys.py)

Avvio: uvicorn --factory converter.app:create_app
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, Form, Request, Security, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.background import BackgroundTask

from . import __version__, apikeys, i18n, pdftools, webhooks
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

Gli errori rispondono con JSON `{"detail": "..."}` e un codice HTTP. I messaggi sono in italiano;
con `Accept-Language: en` (o un'altra lingua diversa dall'italiano) errori, passaggi e note arrivano in inglese.

Esempio: `curl -H "apikey: uconv_..." -F file=@relazione.docx -F target=pdf http://host:8080/api/jobs`"""


# programmi esterni usati dalle conversioni: nome -> eseguibili (ne basta uno)
PROGRAMS = {
    "LibreOffice": ["soffice"], "Pandoc": ["pandoc"], "FFmpeg": ["ffmpeg"], "ImageMagick": ["magick", "convert"],
    "Calibre": ["ebook-convert"], "Poppler": ["pdftoppm"], "Ghostscript": ["gs"], "LibRaw": ["dcraw_emu"],
    "librsvg": ["rsvg-convert"], "Xournal++": ["xournalpp"], "bsdtar": ["bsdtar"], "7-Zip": ["7z", "7zz"],
    "qpdf": ["qpdf"], "OCRmyPDF": ["ocrmypdf"], "Tesseract": ["tesseract"],
}
MAX_ZIP_JOBS = 200


@lru_cache(maxsize=1)
def programs() -> dict[str, bool]:
    """Quali programmi di conversione sono installati (letto una volta: non cambiano a servizio avviato)."""
    return {name: any(shutil.which(b) for b in bins) for name, bins in PROGRAMS.items()}


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


def create_app(settings: Settings | None = None, graph: Graph | None = None,
               pdf_tools: dict[str, pdftools.PdfTool] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    graph = graph or default_graph(settings.disabled)
    pdf_tools = pdftools.available_tools() if pdf_tools is None else pdf_tools
    manager = JobManager(settings, graph)
    keys = apikeys.KeyStore(settings.keys_dir, settings.admin_password, settings.require_key, settings.admin_login)
    set_file_size_limit(settings.max_output_bytes)
    csp_page = ("default-src 'self'; script-src 'self' " + _inline_hashes("index.html", "admin.html", "docs-it.html", "docs-en.html") +
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

    def lang_of(request: Request) -> str:
        return i18n.pick(request.headers.get("accept-language"))

    def error_response(request: Request, exc: JobError) -> JSONResponse:
        lg = lang_of(request)
        return JSONResponse({"detail": i18n.t(str(exc), lg)}, status_code=exc.status, headers={"Content-Language": lg})

    def job_args(request: Request, callback_url: str) -> dict:
        """Chiave che fa la richiesta (con i suoi limiti), lingua e webhook per un nuovo lavoro."""
        kid = getattr(request.state, "key_id", "")
        try:
            cb = webhooks.check_url(callback_url, settings.webhook_hosts)
        except ValueError as e:
            raise JobError(400, str(e)) from None
        return {"key_id": kid, "limits": keys.limits(kid) if kid else None, "callback_url": cb,
                "lang": lang_of(request)}

    def public(request: Request, job) -> dict:
        """Stato del lavoro, con errore, passaggio e nota nella lingua della richiesta."""
        d, lg = manager.public(job), lang_of(request)
        for k in ("error", "step", "note"):
            if d.get(k):
                d[k] = i18n.t(d[k], lg)
        return d

    @app.exception_handler(JobError)
    async def job_error(request: Request, exc: JobError):
        return error_response(request, exc)

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
                    request.state.key_id = keys.check_key(key, perm)
                elif keys.require_key and not keys.verify("session", request.cookies.get(apikeys.SESSION_COOKIE)):
                    raise JobError(401, "Serve una chiave API nell'intestazione 'apikey'")
        except JobError as e:
            return security_headers(request, error_response(request, e))
        return security_headers(request, await call_next(request))

    # ------------------------------------------------------------ pagine

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        resp = HTMLResponse(page("index.html"), headers={"Cache-Control": "no-cache"})
        resp.set_cookie(apikeys.SESSION_COOKIE, keys.sign("session", apikeys.SESSION_TTL),
                        max_age=apikeys.SESSION_TTL, httponly=True, samesite="strict")
        return resp

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    async def docs(request: Request, lang: str = ""):
        """Documentazione in italiano o in inglese (?lang=it|en, altrimenti dalla lingua del browser)."""
        if lang not in ("it", "en"):
            lang = "en" if i18n.pick(request.headers.get("accept-language")) == "en" else "it"
        # generate da docs/documentazione.md e docs/documentation.md durante la build dell'immagine
        doc = STATIC / f"docs-{lang}.html"
        if not doc.exists():
            raise JobError(404, "Documentazione non generata: vedi docs/documentazione.md")
        return FileResponse(doc, media_type="text/html", headers={"Cache-Control": "no-cache", "Content-Language": lang})

    @app.get("/static/i18n.js", include_in_schema=False)
    async def i18n_js():
        return FileResponse(STATIC / "i18n.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/metrics", tags=["Servizio"], response_class=PlainTextResponse)
    async def metrics():
        """Metriche per Prometheus (dall'avvio del servizio): lavori per tipo ed esito, durata, coda, byte caricati,
        webhook, richieste rifiutate dai limiti delle chiavi. Non richiede la chiave; METRICS=false la spegne."""
        if not settings.metrics:
            raise JobError(404, "Metriche disattivate (METRICS=false)")
        st, out = manager.stats(), []

        def metric(name: str, kind: str, help_: str, rows: list[tuple[dict, float]]):
            out.append(f"# HELP uconv_{name} {help_}")
            out.append(f"# TYPE uconv_{name} {kind}")
            for labels, v in rows:
                lab = ",".join(f'{k}="{val}"' for k, val in labels.items())
                out.append(f"uconv_{name}{{{lab}}} {v:g}" if lab else f"uconv_{name} {v:g}")

        metric("info", "gauge", "Version of the service", [({"version": __version__}, 1)])
        metric("jobs_finished_total", "counter", "Finished jobs by kind (convert or PDF tool) and state",
               [({"kind": k, "state": s}, n) for (k, s), n in sorted(manager.completed.items())])
        metric("job_duration_seconds_total", "counter", "Total running time of finished jobs by kind",
               [({"kind": k}, v) for k, v in sorted(manager.duration.items())])
        metric("jobs", "gauge", "Jobs in memory by state",
               [({"state": "queued"}, st["queued"]), ({"state": "running"}, st["running"]),
                ({"state": "kept"}, st["jobs"] - st["queued"] - st["running"])])
        metric("upload_bytes_total", "counter", "Bytes uploaded", [({}, manager.bytes_in)])
        metric("webhooks_total", "counter", "Webhook deliveries by result",
               [({"result": r}, manager.webhooks[r]) for r in ("ok", "error")])
        metric("rejected_total", "counter", "Requests refused by API key limits",
               [({"reason": r}, manager.rejected[r]) for r in ("jobs", "daily")])
        return PlainTextResponse("\n".join(out) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/healthz", tags=["Servizio"])
    async def healthz():
        """Stato del servizio e programmi di conversione installati: non richiede la chiave."""
        return {"ok": True, "version": __version__, **manager.stats(), "programs": programs()}

    # ------------------------------------------------------------ API

    @app.get("/api/formats", **api)
    async def formats():
        """Formati e combinazioni supportate. Permesso: `formats`."""
        return graph.payload() | {"retain_hours": settings.retain_hours,
                                  "max_upload_bytes": settings.max_upload_bytes,
                                  "plico_url": settings.plico_url}

    @app.get("/api/plan/{src}/{dst}", **api)
    async def plan(src: str, dst: str):
        """Passaggi previsti per una conversione. Permesso: `formats`."""
        steps = graph.plan(src, dst)
        if not steps:
            raise JobError(404, "Conversione non supportata")
        return [{"tool": e.tool, "from": e.src, "to": e.dst} for e in steps]

    @app.post("/api/jobs", status_code=201, **api)
    async def create_job(request: Request, file: UploadFile = File(...), target: str = Form(...), meta: str = Form(""),
                         callback_url: str = Form("")):
        """Crea un lavoro caricando un file e indicando il formato di destinazione. Con `callback_url` il server
        chiama quell'indirizzo (POST, JSON) quando il lavoro finisce. Permesso: `convert`."""
        job = await manager.create(file, file.filename, target, meta, **job_args(request, callback_url))
        return public(request, job)

    @app.get("/api/pdf", **api)
    async def pdf_list():
        """Strumenti PDF disponibili (unire, dividere, ruotare, comprimere, OCR...) e loro opzioni. Permesso: `formats`."""
        return {"tools": [t.public() for t in pdf_tools.values()], "max_upload_bytes": settings.max_upload_bytes}

    @app.post("/api/pdf/{tool}", status_code=201, **api)
    async def pdf_job(request: Request, tool: str, files: list[UploadFile] = File(...), pages: str = Form(""), angle: str = Form(""),
                      level: str = Form(""), lang: str = Form(""), force: str = Form(""), meta: str = Form(""),
                      callback_url: str = Form("")):
        """Avvia uno strumento PDF. Si caricano uno o piu' PDF nel campo `files` (per *merge* nell'ordine voluto)
        e le opzioni dello strumento: `pages` (es. `1-3, 5, 8-`), `angle` (90, 180, 270), `level` (low, medium,
        high), `lang` (lingue di Tesseract, es. `ita+eng`), `force` (true per rifare l'OCR).
        Lo stato e il risultato si leggono con `/api/jobs/{id}`. Permesso: `convert`."""
        t = pdf_tools.get(tool)
        if not t:
            raise JobError(404, f"Strumento PDF sconosciuto: {tool}")
        try:
            opts = t.parse({"pages": pages, "angle": angle, "level": level, "lang": lang, "force": force})
        except pdftools.OptionError as e:
            raise JobError(400, str(e)) from None
        args = job_args(request, callback_url)
        job = await manager.create_tool([(f, f.filename) for f in files], t, opts, meta, args.pop("lang"), **args)
        return public(request, job)

    @app.post("/api/jobs/zip", **api)
    async def jobs_zip(request: Request, ids: str = Form(...), lang: str = Form("")):
        """Scarica in un unico ZIP i risultati di piu' lavori finiti (`ids` separati da virgole, al massimo 200;
        quelli non pronti vengono saltati). Permesso: `jobs`."""
        wanted = [i for i in dict.fromkeys(x.strip() for x in ids.split(",")) if i][:MAX_ZIP_JOBS]
        jobs = [j for j in (manager.jobs.get(i) for i in wanted) if j and j.state == "done" and j.out_path]
        if not jobs:
            raise JobError(404, "Nessun risultato pronto da scaricare")
        lg = lang if lang in ("it", "en") else lang_of(request)
        tmp = Path(tempfile.mkdtemp(dir=settings.work_dir))
        out, used = tmp / "results.zip", set()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for j in jobs:
                name, n = j.out_name, 1
                while name in used:  # due risultati con lo stesso nome: "foto (2).jpg"
                    n += 1
                    stem, dot, ext = j.out_name.rpartition(".")
                    name = f"{stem} ({n}).{ext}" if dot else f"{j.out_name} ({n})"
                used.add(name)
                z.write(j.out_path, name)
        return FileResponse(out, filename="converted.zip" if lg == "en" else "convertiti.zip",
                            media_type="application/zip",
                            background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))

    @app.get("/api/jobs/{job_id}", **api)
    async def job_status(request: Request, job_id: str):
        """Stato del lavoro: queued, running, done o error. Permesso: `jobs`."""
        return public(request, manager.get(job_id))

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
        return {"keys": [k | {"used_today_mb": round(manager.used_today(k["id"]) / 1024**2, 1),
                              "active": manager.active(k["id"])} for k in keys.list()]}

    @app.post("/admin/api/keys", include_in_schema=False)
    async def keys_create(request: Request, name: str = Body(...), perms: list[str] = Body(...),
                          max_jobs: int | None = Body(None), max_daily_mb: int | None = Body(None)):
        admin_only(request, write=True)
        key, rec = keys.create(name, perms, max_jobs, max_daily_mb)
        return {"key": key, **rec}

    @app.put("/admin/api/keys/{kid}", include_in_schema=False)
    async def keys_update(request: Request, kid: str, body: dict = Body(...)):
        admin_only(request, write=True)
        extra = {k: body[k] for k in ("max_jobs", "max_daily_mb") if k in body}
        return keys.update(kid, body.get("name"), body.get("perms"), **extra)

    @app.delete("/admin/api/keys/{kid}", include_in_schema=False)
    async def keys_delete(request: Request, kid: str):
        admin_only(request, write=True)
        keys.delete(kid)
        return {"ok": True}

    return app
