"""Applicazione web: pagina su / e API JSON su /api.

API
  GET    /healthz                     stato del servizio
  GET    /api/formats                 {"inputs": {ext: [target...]}, "categories": {...}, "tools": [...]}
  GET    /api/plan/{src}/{dst}        passaggi previsti per una conversione
  POST   /api/jobs                    multipart: file, target, [meta]  -> 201 + stato del lavoro
  GET    /api/jobs/{id}               stato: queued | running | done | error
  GET    /api/jobs/{id}/download      risultato
  DELETE /api/jobs/{id}               cancella subito i file del lavoro
  GET    /docs                        documentazione

Avvio: uvicorn --factory converter.app:create_app
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__
from .config import Settings
from .graph import Graph, default_graph
from .jobs import JobError, JobManager
from .runner import set_file_size_limit

STATIC = Path(__file__).parent / "static"


@lru_cache(maxsize=1)
def index_html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def create_app(settings: Settings | None = None, graph: Graph | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    graph = graph or default_graph(settings.disabled)
    manager = JobManager(settings, graph)
    set_file_size_limit(settings.max_output_bytes)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()
        yield
        await manager.stop()

    app = FastAPI(title="Universal Converter", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager

    @app.exception_handler(JobError)
    async def job_error(_: Request, exc: JobError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(index_html(), headers={"Cache-Control": "no-cache"})

    @app.get("/docs", response_class=HTMLResponse)
    async def docs():
        page = STATIC / "docs.html"  # generata da docs/documentazione.md durante la build dell'immagine
        if not page.exists():
            raise JobError(404, "Documentazione non generata: vedi docs/documentazione.md")
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "version": __version__, **manager.stats()}

    @app.get("/api/formats")
    async def formats():
        return graph.payload() | {"retain_hours": settings.retain_hours,
                                  "max_upload_bytes": settings.max_upload_bytes}

    @app.get("/api/plan/{src}/{dst}")
    async def plan(src: str, dst: str):
        steps = graph.plan(src, dst)
        if not steps:
            raise JobError(404, "Conversione non supportata")
        return [{"tool": e.tool, "from": e.src, "to": e.dst} for e in steps]

    @app.post("/api/jobs", status_code=201)
    async def create_job(file: UploadFile = File(...), target: str = Form(...), meta: str = Form("")):
        job = await manager.create(file, file.filename, target, meta)
        return manager.public(job)

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str):
        return manager.public(manager.get(job_id))

    @app.get("/api/jobs/{job_id}/download")
    async def job_download(job_id: str):
        job = manager.get(job_id)
        if job.state != "done" or not job.out_path:
            raise JobError(409, "Non ancora pronto")
        return FileResponse(job.out_path, filename=job.out_name, media_type="application/octet-stream")

    @app.delete("/api/jobs/{job_id}")
    async def job_delete(job_id: str):
        manager.drop(manager.get(job_id))
        return {"ok": True}

    return app

