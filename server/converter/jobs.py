"""Coda dei lavori: caricamento, esecuzione dei passaggi e pulizia.

I lavori vivono solo in memoria; i loro file stanno in WORK_DIR/jobs/<id> e vengono cancellati
RETAIN_HOURS dopo la fine (o subito, con DELETE). Al riavvio la cartella viene svuotata.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from . import fetch, i18n, options, preview, webhooks, webpage
from .config import Settings
from .formats import ext_of, is_graphviz, normalize, safe_filename, stem_of
from .graph import Graph
from .runner import ConvError, run

if TYPE_CHECKING:
    from .pdftools import PdfTool

CHUNK = 4 * 1024 * 1024
JANITOR_EVERY = 600
STAGED_HOURS = 1.0  # file scaricati da un indirizzo e non ancora convertiti


class Upload(Protocol):
    async def read(self, size: int = -1) -> bytes: ...

MAX_BATCH_FILES = 2000  # file di un archivio convertiti in blocco
SUBTITLE_EXTS = ("srt", "vtt", "ass", "ssa")
MAX_SUBTITLES_BYTES = 10 * 1024 * 1024
STATE_FILE = "job.json"  # stato del lavoro su disco: con KEEP_JOBS sopravvive al riavvio


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
    note: str = ""                       # informazione per l'utente sul risultato (es. "ridotto del 40%")
    tool: PdfTool | None = None          # strumento PDF al posto di una conversione
    opts: dict = field(default_factory=dict)
    lang: str = "it"                    # lingua del nome del risultato (strumenti PDF)
    inputs: list[Path] = field(default_factory=list)  # file caricati per uno strumento PDF
    key_id: str = ""                     # chiave API che ha creato il lavoro ("" = pagina web o nessuna chiave)
    callback_url: str = ""               # webhook da chiamare alla fine
    webhook: str = ""                    # esito del webhook: "", "ok" o l'errore
    size_in: int = 0                     # byte caricati
    options: dict = field(default_factory=dict)  # opzioni di conversione (options.py)
    preview: str = ""                    # tipo di anteprima del risultato (preview.py)
    batch: bool = False                  # archivio: ogni file contenuto convertito in ``target``
    extras: dict = field(default_factory=dict)  # file in piu' (es. "subtitles": percorso dei sottotitoli da aggiungere)
    task: asyncio.Task | None = field(default=None, repr=False)
    tool_name: str = ""                  # nome dello strumento PDF (per riprenderlo dopo un riavvio)

    @property
    def input_path(self) -> Path:
        return self.dir / f"input.{self.src_ext}"

    def input_files(self) -> list[Path]:
        return self.inputs or [self.input_path]


@dataclass
class Staged:
    """File scaricato da un indirizzo, in attesa che l'utente scelga il formato."""
    id: str
    path: Path
    name: str
    size: int
    key_id: str = ""
    created: float = field(default_factory=time.time)


class JobManager:
    def __init__(self, settings: Settings, graph: Graph):
        self.settings = settings
        self.graph = graph
        self.jobs: dict[str, Job] = {}
        self._sem: asyncio.Semaphore | None = None
        self._janitor: asyncio.Task | None = None
        self._hooks: set[asyncio.Task] = set()
        # metriche (dall'avvio): lavori finiti per tipo ed esito, durata, byte caricati, webhook
        self.completed = Counter()         # (kind, state) -> numero
        self.duration = Counter()          # kind -> secondi totali
        self.bytes_in = 0
        self.webhooks = Counter()          # "ok" | "error" -> numero
        self.rejected = Counter()          # motivo -> numero (limiti delle chiavi)
        # volume giornaliero per chiave API: (key_id, "AAAA-MM-GG") -> byte (in memoria: si azzera al riavvio)
        self.usage: dict[tuple[str, str], int] = {}
        self.staged: dict[str, Staged] = {}
        self._preview_sem = asyncio.Semaphore(1)
        self.pdf_tools: dict = {}          # nome -> PdfTool, per riprendere dopo un riavvio gli strumenti PDF in coda
        self.restored = 0                  # lavori ripresi all'avvio (KEEP_JOBS)
        self._stopping = False

    # -------------------------------------------------------------------------------------- ciclo di vita
    async def start(self) -> None:
        self._sem = asyncio.Semaphore(self.settings.max_parallel)
        if not self.settings.keep_jobs:
            shutil.rmtree(self.settings.jobs_dir, ignore_errors=True)  # lavori di un avvio precedente: via
        shutil.rmtree(self.staged_dir, ignore_errors=True)
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.keep_jobs:
            self._restore()
        self._janitor = asyncio.create_task(self._janitor_loop())

    # --------------------------------------------------------------------------- stato su disco (KEEP_JOBS)
    def _persist(self, job: Job) -> None:
        """Scrive job.json nella cartella del lavoro (percorsi relativi alla cartella)."""
        if not self.settings.keep_jobs or not job.dir.exists():
            return
        rel = lambda p: str(Path(p).relative_to(job.dir)) if p else ""  # noqa: E731
        data = {"version": 1, "id": job.id, "filename": job.filename, "src_ext": job.src_ext, "target": job.target,
                "meta": job.meta, "state": job.state, "created": job.created, "started": job.started,
                "finished": job.finished, "error": job.error, "out_path": rel(job.out_path),
                "out_name": job.out_name, "note": job.note, "tool": job.tool.name if job.tool else "",
                "opts": job.opts, "lang": job.lang, "inputs": [rel(p) for p in job.inputs], "key_id": job.key_id,
                "callback_url": job.callback_url, "webhook": job.webhook, "size_in": job.size_in,
                "options": job.options, "preview": job.preview, "batch": job.batch,
                "extras": {k: rel(v) for k, v in job.extras.items()}}
        tmp = job.dir / f"{STATE_FILE}.tmp"
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(job.dir / STATE_FILE)
        except (OSError, TypeError, ValueError):
            tmp.unlink(missing_ok=True)

    def _restore(self) -> None:
        """Riprende i lavori di un avvio precedente: quelli finiti restano scaricabili fino alla scadenza, quelli
        in coda o interrotti ripartono da capo; il resto (scaduti, senza stato, file mancanti) viene cancellato."""
        now = time.time()
        for d in sorted(self.settings.jobs_dir.iterdir(), key=lambda p: p.stat().st_mtime):
            job = self._load(d) if d.is_dir() and re.fullmatch(r"[0-9a-f]{32}", d.name) else None
            if job is None:
                shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)
                continue
            if job.state in ("done", "error"):
                expired = now - job.finished > self.settings.retain_hours * 3600
                if expired or (job.state == "done" and not (job.out_path and job.out_path.exists())):
                    shutil.rmtree(d, ignore_errors=True)
                    continue
                self.jobs[job.id] = job
            else:  # in coda o interrotto a meta': si ricomincia dai file caricati
                if not all(f.exists() for f in job.input_files()) or (job.tool is None and job.tool_name):
                    shutil.rmtree(d, ignore_errors=True)
                    continue
                for sub in d.iterdir():
                    if sub.is_dir():
                        shutil.rmtree(sub, ignore_errors=True)
                job.state, job.progress, job.step, job.started, job.out_path = "queued", None, "", 0.0, None
                self.jobs[job.id] = job
                job.task = asyncio.create_task(self._process(job))
            self.restored += 1

    def _load(self, d: Path) -> Job | None:
        try:
            data = json.loads((d / STATE_FILE).read_text(encoding="utf-8"))
            if data.get("version") != 1 or data["id"] != d.name:
                return None
            ab = lambda r: d / r if r else None  # noqa: E731
            job = Job(id=data["id"], dir=d, filename=data["filename"], src_ext=data["src_ext"], target=data["target"],
                      meta=data["meta"], state=data["state"], created=data["created"], started=data["started"],
                      finished=data["finished"], error=data["error"], out_path=ab(data["out_path"]),
                      out_name=data["out_name"], note=data["note"], opts=data["opts"], lang=data["lang"],
                      inputs=[d / r for r in data["inputs"]], key_id=data["key_id"],
                      callback_url=data["callback_url"], webhook=data["webhook"], size_in=data["size_in"],
                      options=data["options"], preview=data["preview"], batch=data["batch"],
                      extras={k: str(d / v) for k, v in data["extras"].items()})
        except (OSError, ValueError, KeyError, TypeError):
            return None
        job.tool_name = data.get("tool", "")
        job.tool = self.pdf_tools.get(job.tool_name) if job.tool_name else None
        if any(".." in Path(p).parts for p in [*data["inputs"], data["out_path"], *data["extras"].values()]):
            return None
        return job

    async def stop(self) -> None:
        self._stopping = True
        tasks = [t for t in [self._janitor, *self._hooks, *(j.task for j in self.jobs.values())] if t and not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    @property
    def staged_dir(self) -> Path:
        return self.settings.work_dir / "staged"

    # ------------------------------------------------------------------------------------------- lavori
    async def create(self, upload: Upload | None, filename: str | None, target: str, meta: str = "", *,
                     opts: str | dict | None = None, staged: str = "", lang: str = "it", key_id: str = "",
                     limits: dict | None = None, callback_url: str = "",
                     subtitles: tuple[Upload, str] | None = None) -> Job:
        """Nuovo lavoro da un file caricato oppure (``staged``) da un file gia' scaricato con stage_url().
        ``subtitles``: (file, nome) dei sottotitoli da aggiungere a un video."""
        st = None
        if staged:
            st = self.staged.get(staged)
            if not st or st.key_id != key_id:
                raise JobError(404, "File scaricato non trovato (scaduto o server riavviato)")
            filename = st.name
            if filename.lower().endswith(".dot"):
                with st.path.open("rb") as fh:
                    if is_graphviz(fh.read(1024)):
                        filename = filename[:-4] + ".gv"
        name = safe_filename(filename)
        src, target = ext_of(name), normalize(target)
        plan = self.graph.plan(src, target)
        batch = not plan and self.graph.is_batch(src, target)
        if not plan and not batch:
            raise JobError(400, f"Non so convertire .{src or '?'} in .{target}")
        try:
            clean = options.parse(opts, plan, target)
        except options.OptionError as e:
            raise JobError(400, str(e)) from None
        subs_ext = ""
        if subtitles:
            subs_ext = ext_of(safe_filename(subtitles[1]))
            if "subtitles" not in options.applicable(plan, target):
                raise JobError(400, "I sottotitoli si possono aggiungere solo a un video")
            if subs_ext not in SUBTITLE_EXTS:
                raise JobError(400, f"Sottotitoli non riconosciuti: .{subs_ext or '?'} (servono SRT, VTT o ASS)")
        elif clean.get("burn_subtitles"):
            raise JobError(400, "Manca il file dei sottotitoli")
        if len(self.jobs) >= self.settings.max_queue:
            raise JobError(503, "Troppi lavori in corso: riprova tra poco")
        budget = None if st else self._check_limits(key_id, limits)
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, dir=self.settings.jobs_dir / job_id, filename=name, src_ext=src, target=target,
                  meta=meta[:2000], lang=lang, key_id=key_id, callback_url=callback_url, options=clean, batch=batch)
        job.dir.mkdir(parents=True)
        if subtitles:
            subs_path = job.dir / f"subs.{subs_ext}"
            try:
                n = await self._save(subtitles[0], subs_path, None)
            except BaseException:
                shutil.rmtree(job.dir, ignore_errors=True)
                raise
            if not 0 < n <= MAX_SUBTITLES_BYTES:
                shutil.rmtree(job.dir, ignore_errors=True)
                raise JobError(400, "File dei sottotitoli vuoto o troppo grande (al massimo 10 MB)")
            job.extras["subtitles"] = str(subs_path)
        if st:  # gia' contato nel volume della chiave quando e' stato scaricato
            self.staged.pop(st.id, None)
            shutil.move(st.path, job.input_path)
            shutil.rmtree(st.path.parent, ignore_errors=True)
            job.size_in = st.size
        else:
            assert upload is not None
            try:
                size = await self._save(upload, job.input_path, budget)
            except BaseException:
                shutil.rmtree(job.dir, ignore_errors=True)
                raise
            if size == 0:
                shutil.rmtree(job.dir, ignore_errors=True)
                raise JobError(400, "File vuoto")
            self._account(job, size)
        self.jobs[job.id] = job
        self._persist(job)
        job.task = asyncio.create_task(self._process(job))
        return job

    async def stage_url(self, url: str, *, key_id: str = "", limits: dict | None = None,
                        article: bool = False) -> Staged:
        """Scarica un file da un indirizzo e lo tiene da parte finche' non si sceglie il formato.

        Con ``article`` una pagina HTML diventa il suo articolo principale, con le immagini incorporate."""
        if not self.settings.url_import:
            raise JobError(404, "Importazione da indirizzo disattivata (URL_IMPORT=false)")
        if len(self.staged) >= self.settings.max_queue:
            raise JobError(503, "Troppi lavori in corso: riprova tra poco")
        budget = self._check_limits(key_id, limits)
        sid = uuid.uuid4().hex
        d = self.staged_dir / sid
        d.mkdir(parents=True)
        limit = self.settings.max_upload_bytes if budget is None else min(budget, self.settings.max_upload_bytes)
        try:
            name, mime_ext, size = await asyncio.to_thread(fetch.download, url, d / "download", limit,
                                                           self.settings.url_allow_private)
        except fetch.FetchError as e:
            shutil.rmtree(d, ignore_errors=True)
            if e.status == 413 and budget is not None and budget < self.settings.max_upload_bytes:
                self.rejected["daily"] += 1
                raise JobError(429, "Limite giornaliero della chiave superato") from None
            raise JobError(e.status, str(e)) from None
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        name = safe_filename(name)
        if mime_ext and not self.graph.targets(ext_of(name)) and self.graph.targets(mime_ext):
            name = f"{stem_of(name)}.{mime_ext}"  # "pagina" o "download.php" -> estensione dal Content-Type
        if article and ext_of(name) in ("html", "htm"):
            try:
                title, page = await asyncio.to_thread(webpage.article, (d / "download").read_bytes(), url,
                                                      self.settings.url_allow_private)
            except Exception:  # noqa: BLE001 - pagina che non si riesce a leggere: resta l'HTML originale
                pass
            else:
                (d / "download").write_text(page, encoding="utf-8")
                name, size = safe_filename(f"{title[:120]}.html"), (d / "download").stat().st_size
        st = Staged(id=sid, path=d / "download", name=name, size=size, key_id=key_id)
        self.staged[sid] = st
        self.bytes_in += size
        if key_id:
            k = (key_id, self.today())
            self.usage[k] = self.usage.get(k, 0) + size
        return st

    async def create_tool(self, uploads: list[tuple[Upload, str | None]], tool: PdfTool, opts: dict,
                          meta: str = "", lang: str = "it", *, key_id: str = "", limits: dict | None = None,
                          callback_url: str = "") -> Job:
        """Lavoro di uno strumento PDF: uno o piu' file caricati, nell'ordine ricevuto."""
        if not tool.min_files <= len(uploads) <= tool.max_files:
            if tool.max_files == 1:
                raise JobError(400, f"{tool.title}: carica un PDF alla volta")
            raise JobError(400, f"{tool.title}: servono da {tool.min_files} a {tool.max_files} PDF")
        names = [safe_filename(name) for _, name in uploads]
        bad = [n for n in names if ext_of(n) != "pdf"]
        if bad:
            raise JobError(400, f"{tool.title} accetta solo PDF: {bad[0]}")
        if len(self.jobs) >= self.settings.max_queue:
            raise JobError(503, "Troppi lavori in corso: riprova tra poco")
        budget = self._check_limits(key_id, limits)
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, dir=self.settings.jobs_dir / job_id, filename=names[0], src_ext="pdf",
                  target="zip" if tool.name == "split" else "pdf", meta=meta[:2000], tool=tool, opts=opts, lang=lang,
                  key_id=key_id, callback_url=callback_url)
        job.dir.mkdir(parents=True)
        total = 0
        try:
            for i, (upload, _) in enumerate(uploads, 1):
                path = job.dir / f"input-{i:03d}.pdf"
                size = await self._save(upload, path, None if budget is None else budget - total)
                if size == 0:
                    raise JobError(400, f"File vuoto: {names[i - 1]}")
                total += size
                job.inputs.append(path)
        except BaseException:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise
        self._account(job, total)
        self.jobs[job.id] = job
        self._persist(job)
        job.task = asyncio.create_task(self._process(job))
        return job

    async def _save(self, upload: Upload, dest: Path, budget: int | None = None) -> int:
        """Salva un file caricato; ``budget`` = byte ancora ammessi oggi per la chiave (None = senza limite)."""
        size = 0
        with dest.open("wb") as fh:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > self.settings.max_upload_bytes:
                    raise JobError(413, "File troppo grande")
                if budget is not None and size > budget:
                    self.rejected["daily"] += 1
                    raise JobError(429, "Limite giornaliero della chiave superato")
                fh.write(chunk)
        return size

    # ------------------------------------------------------------------------------- limiti delle chiavi
    @staticmethod
    def today() -> str:
        return time.strftime("%Y-%m-%d")

    def used_today(self, key_id: str) -> int:
        return self.usage.get((key_id, self.today()), 0)

    def active(self, key_id: str) -> int:
        return sum(1 for j in self.jobs.values() if j.key_id == key_id and j.state in ("queued", "running"))

    def _check_limits(self, key_id: str, limits: dict | None) -> int | None:
        """Lavori contemporanei e volume giornaliero della chiave; restituisce i byte ancora ammessi oggi."""
        if not key_id or not limits:
            return None
        max_jobs, max_mb = limits.get("max_jobs"), limits.get("max_daily_mb")
        if max_jobs and self.active(key_id) >= max_jobs:
            self.rejected["jobs"] += 1
            raise JobError(429, f"La chiave ha gia' {max_jobs} lavori in corso: riprova quando finiscono")
        if not max_mb:
            return None
        left = max_mb * 1024 * 1024 - self.used_today(key_id)
        if left <= 0:
            self.rejected["daily"] += 1
            raise JobError(429, "Limite giornaliero della chiave superato")
        return left

    def _account(self, job: Job, size: int) -> None:
        job.size_in = size
        self.bytes_in += size
        if job.key_id:
            k = (job.key_id, self.today())
            self.usage = {kk: v for kk, v in self.usage.items() if kk[1] == k[1]}  # solo oggi
            self.usage[k] = self.usage.get(k, 0) + size

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
        if job.tool:
            d |= {"tool": job.tool.name, "files": len(job.inputs)}
        if job.note:
            d["note"] = job.note
        if job.options:
            d["options"] = job.options
        if job.preview:
            d["preview"] = job.preview
        if job.callback_url:
            d["webhook"] = job.webhook or "pending"
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
                await (self._run_tool(job) if job.tool else self._run_batch(job) if job.batch else self._run_steps(job))
                job.state, job.progress, job.step = "done", 1.0, ""
                if self.settings.previews and job.out_path:
                    job.preview = preview.kind(job.out_path, job.out_name, self.graph)
            except asyncio.CancelledError:
                if self._stopping and self.settings.keep_jobs:
                    job.state, job.progress, job.step = "queued", None, ""  # servizio che si ferma: riparte al riavvio
                else:
                    job.state, job.error = "error", "annullato"
                raise
            except ConvError as e:
                job.state, job.error = "error", self._clean(job, str(e))
            except Exception as e:  # noqa: BLE001 - qualsiasi errore va mostrato, non deve bloccare la coda
                job.state, job.error = "error", self._clean(job, f"errore interno: {e!r}")
            finally:
                self._finish(job)

    def _finish(self, job: Job) -> None:
        """Fine di un lavoro: cancella i file caricati, salva lo stato, conta le metriche, chiama il webhook.
        Un lavoro interrotto dallo spegnimento (di nuovo "queued") tiene file e stato per il riavvio."""
        if job.state == "queued":
            self._persist(job)
            return
        job.finished = time.time()
        for f in job.input_files():
            f.unlink(missing_ok=True)
        self._persist(job)
        kind = job.tool.name if job.tool else "convert"
        self.completed[(kind, job.state)] += 1
        self.duration[kind] += job.finished - job.started
        if job.callback_url and job.state in ("done", "error"):
            t = asyncio.create_task(self._webhook(job))
            self._hooks.add(t)
            t.add_done_callback(self._hooks.discard)

    @staticmethod
    def _clean(job: Job, msg: str) -> str:
        """Toglie dai messaggi d'errore i percorsi interni (/work/jobs/<id>/step1/...): resta il nome del file."""
        msg = re.sub(re.escape(str(job.dir)) + r"/(batch/(in/)?(\d+/)?)?(step\d+/)?", "", msg)
        return re.sub(r"(/[\w.-]+)*/jobs/[0-9a-f]{32}/(batch/(in/)?(\d+/)?)?(step\d+/)?", "", msg)

    def payload(self, job: Job) -> dict:
        """Stato del lavoro per il webhook, nella lingua del lavoro."""
        d = self.public(job)
        for k in ("error", "step", "note"):
            if d.get(k):
                d[k] = i18n.t(d[k], job.lang)
        return d

    async def _webhook(self, job: Job) -> None:
        job.webhook = await webhooks.deliver(job.callback_url, self.payload(job), self.settings.webhook_secret)
        self.webhooks["ok" if job.webhook == "ok" else "error"] += 1

    async def _run_steps(self, job: Job) -> None:
        cur = await self._convert(job, job.input_path, job.src_ext, job.target, job.dir)
        multi = cur.suffix == ".zip" and job.target != "zip"  # piu' file (es. pagine di un PDF) in uno zip
        job.out_path = cur
        job.out_name = f"{stem_of(job.filename)}.{'zip' if multi else job.target}"

    async def _convert(self, job: Job, inp: Path, src: str, target: str, base: Path, prefix: str = "") -> Path:
        """Esegue i passaggi del percorso src -> target, ognuno in base/stepN; restituisce il file finale."""
        path = self.graph.plan(src, target)
        if not path:
            raise ConvError(f"conversione {src} -> {target} non supportata")
        cur = inp
        for i, edge in enumerate(path, 1):
            job.step = f"{prefix}{edge.tool}: {edge.src.upper()} → {edge.dst.upper()}"
            if len(path) > 1:
                job.step += f" ({i}/{len(path)})"
            if not prefix:
                job.progress = None
            wd = base / f"step{i}"
            wd.mkdir()
            out = await edge.fn(job, cur, edge.dst, wd)
            if not out.exists() or out.stat().st_size == 0:
                raise ConvError(f"{edge.tool} ha prodotto un file vuoto")
            if out.suffix != ".zip" or edge.dst == "zip":
                out = out.rename(wd / f"input.{edge.dst}")  # l'estensione serve al passaggio dopo
            cur = out
        return cur

    async def _run_batch(self, job: Job) -> None:
        """Conversione in blocco: estrae l'archivio, converte ogni file che puo' arrivare a ``target`` (gli altri
        vengono saltati e i file gia' nel formato copiati) e rimette tutto in uno ZIP con le stesse cartelle."""
        root = job.dir / "batch"
        tree, out_tree = root / "in", root / "out"
        tree.mkdir(parents=True)
        out_tree.mkdir()
        job.step = "Estrazione dell'archivio"
        await run(["bsdtar", "-xf", str(job.input_path), "-C", str(tree)], timeout=3600)  # niente ../ e percorsi assoluti
        files = sorted(p for p in tree.rglob("*") if p.is_file() and not p.is_symlink()
                       and not any(part.startswith(".") or part == "__MACOSX" for part in p.relative_to(tree).parts))
        if len(files) > MAX_BATCH_FILES:
            raise ConvError(f"troppi file nell'archivio: {len(files)} (al massimo {MAX_BATCH_FILES})")
        converted, copied, skipped, failed = [], [], [], []
        for n, f in enumerate(files, 1):
            rel = f.relative_to(tree)
            src = normalize(ext_of(f.name)) if ext_of(f.name) else ""
            if f.name.lower().endswith(".dot"):
                with f.open("rb") as fh:
                    src = "gv" if is_graphviz(fh.read(1024)) else src
            job.progress = (n - 1) / max(len(files), 1)
            dest = out_tree / rel.parent / f"{stem_of(f.name)}.{job.target}"
            if src == job.target:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out_tree / rel)
                copied.append(str(rel))
                continue
            if not src or not self.graph.plan(src, job.target):
                skipped.append(str(rel))
                continue
            work = root / str(n)
            work.mkdir()
            inp = work / f"input.{src}"
            shutil.move(f, inp)
            try:
                res = await self._convert(job, inp, src, job.target, work, prefix=f"{n}/{len(files)} · ")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if res.suffix == ".zip" and job.target != "zip":  # piu' file (pagine): una cartella col nome del file
                    folder = dest.with_suffix("")
                    folder.mkdir(parents=True, exist_ok=True)
                    await run(["bsdtar", "-xf", str(res), "-C", str(folder)], timeout=3600)
                else:
                    shutil.move(res, dest)
                converted.append(str(rel))
            except ConvError as e:
                failed.append(f"{rel}: {self._clean(job, str(e))}")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        if not converted:
            raise ConvError(f"nessun file dell'archivio si puo' convertire in .{job.target}"
                            + (f" ({len(failed)} non riusciti: {failed[0]})" if failed else ""))
        if skipped or failed:
            report = [i18n.t("Conversione in blocco", job.lang), ""]
            for title, names in (("Convertiti", converted), ("Copiati (gia' nel formato)", copied),
                                 ("Saltati (formato non convertibile)", skipped), ("Non riusciti", failed)):
                if names:
                    report += [f"{i18n.t(title, job.lang)} ({len(names)}):", *[f"  {x}" for x in names], ""]
            (out_tree / ("conversion-report.txt" if job.lang == "en" else "resoconto-conversione.txt")).write_text(
                "\n".join(report), encoding="utf-8")
        job.step, job.progress = "Creazione dello ZIP", None
        out = root / "out.zip"
        await run(["bsdtar", "-a", "-cf", str(out), "-C", str(out_tree), "."], timeout=3600)
        shutil.rmtree(out_tree, ignore_errors=True)
        shutil.rmtree(tree, ignore_errors=True)
        counts = (("convertiti", converted), ("copiati", copied), ("saltati", skipped), ("non riusciti", failed))
        job.note = ", ".join(f"{len(names)} {i18n.t(word, job.lang)}" for word, names in counts
                             if names or word == "convertiti")
        job.out_path, job.out_name = out, f"{stem_of(job.filename)}-{job.target}.zip"

    async def _run_tool(self, job: Job) -> None:
        assert job.tool
        job.step, job.progress = job.tool.title, None
        wd = job.dir / "step1"
        wd.mkdir()
        try:
            out, name = await job.tool.fn(job, job.inputs, job.opts, wd)
        except ValueError as e:  # OptionError: pagine che non esistono in questo PDF
            raise ConvError(str(e)) from None
        if not out.exists() or out.stat().st_size == 0:
            raise ConvError(f"{job.tool.title}: risultato vuoto")
        job.out_path, job.out_name, job.step = out, safe_filename(i18n.filename(name, job.lang)), ""

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(JANITOR_EVERY)
            self.cleanup()

    async def preview(self, job: Job) -> tuple[Path, str]:
        """File d'anteprima del risultato e suo tipo MIME."""
        if job.state != "done" or not job.out_path:
            raise JobError(409, "Non ancora pronto")
        if not job.preview:
            raise JobError(404, "Anteprima non disponibile per questo formato")
        try:
            return await preview.get(job, self.graph, self._preview_sem)
        except preview.PreviewError:
            raise JobError(404, "Anteprima non disponibile per questo file") from None

    def cleanup(self, now: float | None = None) -> int:
        """Cancella i lavori finiti da piu' di RETAIN_HOURS; restituisce quanti ne ha tolti."""
        now = now or time.time()
        for st in [s for s in self.staged.values() if now - s.created > STAGED_HOURS * 3600]:
            self.staged.pop(st.id, None)
            shutil.rmtree(st.path.parent, ignore_errors=True)
        old = [j for j in self.jobs.values() if j.finished and now - j.finished > self.settings.retain_hours * 3600]
        for job in old:
            self.drop(job)
        return len(old)
