"""Coda dei lavori: caricamento, esecuzione dei passaggi e pulizia.

I lavori vivono solo in memoria; i loro file stanno in WORK_DIR/jobs/<id> e vengono cancellati
RETAIN_HOURS dopo la fine (o subito, con DELETE). Al riavvio la cartella viene svuotata.
"""
from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .config import Settings
from .formats import ext_of, normalize, safe_filename, stem_of
from .graph import Graph
from .runner import ConvError

CHUNK = 4 * 1024 * 1024
JANITOR_EVERY = 600


class Upload(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class JobError(Exception):
    """Richiesta non valida; ``status`` e' il codice HTTP da restituire."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Job:
    id: str
    dir: Path
    filename: str
    src_ext: str
    target: str
    meta: str = ""
    state: str = "queued"  # queued | running | done | error
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    progress: float | None = None
    step: str = ""
    error: str = ""
    out_path: Path | None = None
    out_name: str = ""
    task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def input_path(self) -> Path:
        return self.dir / f"input.{self.src_ext}"


class JobManager:
    def __init__(self, settings: Settings, graph: Graph):
        self.settings = settings
        self.graph = graph
        self.jobs: dict[str, Job] = {}
        self._sem: asyncio.Semaphore | None = None
        self._janitor: asyncio.Task | None = None

    # -------------------------------------------------------------------------------------- ciclo di vita
    async def start(self) -> None:
        self._sem = asyncio.Semaphore(self.settings.max_parallel)
        shutil.rmtree(self.settings.jobs_dir, ignore_errors=True)  # lavori di un avvio precedente: orfani
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._janitor = asyncio.create_task(self._janitor_loop())

    async def stop(self) -> None:
        tasks = [t for t in [self._janitor, *(j.task for j in self.jobs.values())] if t and not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    # ------------------------------------------------------------------------------------------- lavori
    async def create(self, upload: Upload, filename: str | None, target: str, meta: str = "") -> Job:
        name = safe_filename(filename)
        src, target = ext_of(name), normalize(target)
        if not self.graph.plan(src, target):
            raise JobError(400, f"Non so convertire .{src or '?'} in .{target}")
        if len(self.jobs) >= self.settings.max_queue:
            raise JobError(503, "Troppi lavori in corso: riprova tra poco")
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, dir=self.settings.jobs_dir / job_id, filename=name, src_ext=src, target=target,
                  meta=meta[:2000])
        job.dir.mkdir(parents=True)
        try:
            size = await self._save(upload, job.input_path)
        except BaseException:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise
        if size == 0:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise JobError(400, "File vuoto")
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._process(job))
        return job

    async def _save(self, upload: Upload, dest: Path) -> int:
        size = 0
        with dest.open("wb") as fh:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > self.settings.max_upload_bytes:
                    raise JobError(413, "File troppo grande")
                fh.write(chunk)
        return size

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if not job:
            raise JobError(404, "Lavoro non trovato (scaduto o server riavviato)")
        return job

    def drop(self, job: Job) -> None:
        if job.task and not job.task.done():
            job.task.cancel()
        shutil.rmtree(job.dir, ignore_errors=True)
        self.jobs.pop(job.id, None)

    def position(self, job: Job) -> int:
        return 1 + sum(1 for j in self.jobs.values() if j.state == "queued" and j.created < job.created)

    def public(self, job: Job) -> dict:
        d = {"id": job.id, "filename": job.filename, "target": job.target, "state": job.state,
             "progress": job.progress, "step": job.step, "error": job.error, "meta": job.meta,
             "created": job.created, "finished": job.finished or None}
        if job.state == "done" and job.out_path:
            d |= {"out_name": job.out_name, "size": job.out_path.stat().st_size}
        if job.state == "queued":
            d["position"] = self.position(job)
        return d

    def stats(self) -> dict:
        return {"jobs": len(self.jobs), "running": sum(j.state == "running" for j in self.jobs.values()),
                "queued": sum(j.state == "queued" for j in self.jobs.values())}

    # ---------------------------------------------------------------------------------------- esecuzione
    async def _process(self, job: Job) -> None:
        assert self._sem, "JobManager.start() non chiamato"
        async with self._sem:
            job.state, job.started = "running", time.time()
            try:
                await self._run_steps(job)
                job.state, job.progress, job.step = "done", 1.0, ""
            except asyncio.CancelledError:
                job.state, job.error = "error", "annullato"
                raise
            except ConvError as e:
                job.state, job.error = "error", str(e)
            except Exception as e:  # noqa: BLE001 - qualsiasi errore va mostrato, non deve bloccare la coda
                job.state, job.error = "error", f"errore interno: {e!r}"
            finally:
                job.finished = time.time()
                job.input_path.unlink(missing_ok=True)

    async def _run_steps(self, job: Job) -> None:
        path = self.graph.plan(job.src_ext, job.target)
        if not path:
            raise ConvError(f"conversione {job.src_ext} -> {job.target} non supportata")
        cur = job.input_path
        for i, edge in enumerate(path, 1):
            job.step = f"{edge.tool}: {edge.src.upper()} → {edge.dst.upper()}"
            if len(path) > 1:
                job.step += f" ({i}/{len(path)})"
            job.progress = None
            wd = job.dir / f"step{i}"
            wd.mkdir()
            out = await edge.fn(job, cur, edge.dst, wd)
            if not out.exists() or out.stat().st_size == 0:
                raise ConvError(f"{edge.tool} ha prodotto un file vuoto")
            if out.suffix != ".zip" or edge.dst == "zip":
                out = out.rename(wd / f"input.{edge.dst}")  # l'estensione serve al passaggio dopo
            cur = out
        multi = cur.suffix == ".zip" and job.target != "zip"  # piu' file (es. pagine di un PDF) in uno zip
        job.out_path = cur
        job.out_name = f"{stem_of(job.filename)}.{'zip' if multi else job.target}"

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(JANITOR_EVERY)
            self.cleanup()

    def cleanup(self, now: float | None = None) -> int:
        """Cancella i lavori finiti da piu' di RETAIN_HOURS; restituisce quanti ne ha tolti."""
        now = now or time.time()
        old = [j for j in self.jobs.values() if j.finished and now - j.finished > self.settings.retain_hours * 3600]
        for job in old:
            self.drop(job)
        return len(old)
