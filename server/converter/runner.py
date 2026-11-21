"""Esecuzione dei programmi esterni."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import zipfile
from pathlib import Path
from typing import Callable


class ConvError(Exception):
    """Conversione fallita: il messaggio viene mostrato all'utente."""


# Dimensione massima di ogni file scritto dai programmi esterni (0 = nessun limite). Protegge il disco da un
# convertitore che entra in un ciclo infinito: oltre il limite il kernel lo ferma con SIGXFSZ.
FILE_SIZE_LIMIT = 0
# Memoria massima (spazio di indirizzi) per i convertitori scritti in Python (pdf2docx, PyMuPDF...): un PDF fatto
# apposta non deve poter occupare tutta la RAM del server. Non vale per LibreOffice e FFmpeg, che riservano molta
# memoria virtuale senza usarla.
MEMORY_LIMIT = 0
_PRLIMIT = shutil.which("prlimit")


def set_file_size_limit(limit: int) -> None:
    global FILE_SIZE_LIMIT
    FILE_SIZE_LIMIT = max(0, int(limit))


def set_memory_limit(limit: int) -> None:
    global MEMORY_LIMIT
    MEMORY_LIMIT = max(0, int(limit))


async def run(cmd: list[str], *, timeout: int = 1800, cwd: Path | None = None,
              on_line: Callable[[str], None] | None = None, env: dict | None = None,
              limit_memory: bool = False) -> str:
    """Esegue un comando senza shell e ne restituisce le ultime righe di output.

    Solleva ConvError se il comando fallisce o supera il tempo; in quel caso termina anche i processi figli.
    """
    name = Path(cmd[0]).name
    limits = ([f"--fsize={FILE_SIZE_LIMIT}"] if FILE_SIZE_LIMIT else []) \
        + ([f"--as={MEMORY_LIMIT}"] if limit_memory and MEMORY_LIMIT else [])
    full = [_PRLIMIT, *limits, "--", *cmd] if limits and _PRLIMIT else cmd
    proc = await asyncio.create_subprocess_exec(
        *full, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **(env or {})}, start_new_session=True)
    tail: list[str] = []

    async def reader():
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if on_line:
                on_line(line)
            tail.append(line)
            del tail[:-40]

    try:
        await asyncio.wait_for(asyncio.gather(reader(), proc.wait()), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(e, asyncio.CancelledError):
            raise
        raise ConvError(f"tempo scaduto dopo {timeout // 60} minuti ({name})") from None
    if proc.returncode == -signal.SIGXFSZ:
        gb = FILE_SIZE_LIMIT / 1024**3
        raise ConvError(f"{name} ha superato la dimensione massima di un file ({gb:g} GB)")
    if proc.returncode != 0:
        msg = "\n".join(line for line in tail if line.strip())[-600:]
        if limit_memory and MEMORY_LIMIT and ("MemoryError" in msg or "std::bad_alloc" in msg or proc.returncode == -9):
            raise ConvError(f"{name} ha superato la memoria massima ({MEMORY_LIMIT / 1024**3:g} GB)")
        raise ConvError(f"{name} ha restituito {proc.returncode}: {msg}")
    return "\n".join(tail)


def single_output(d: Path, pattern: str = "*") -> Path:
    files = sorted(p for p in d.glob(pattern) if p.is_file())
    if not files:
        raise ConvError("il convertitore non ha prodotto nessun file")
    return files[0]


def zip_many(files: list[Path], out: Path) -> Path:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(f, f.name)
    return out
