"""Trascrizione di audio e video (testo, sottotitoli SRT o VTT) con un servizio Whisper separato e facoltativo.

Il modello di riconoscimento e' pesante (centinaia di MB, meglio con una GPU), quindi non sta nell'immagine del
convertitore: gira in un container a parte che offre l'API compatibile con OpenAI
``POST /v1/audio/transcriptions`` (speaches / faster-whisper-server, whisper.cpp con ``--inference-path``,
LocalAI…). Con ``WHISPER_URL`` impostato compaiono le conversioni audio/video -> srt, vtt, txt.

Il file non lascia la rete: FFmpeg estrae l'audio (mono, 16 kHz, MP3 a 48 kbit/s, circa 20 MB per ora) e lo
manda solo all'indirizzo scelto dall'amministratore.
"""
from __future__ import annotations

import asyncio
import http.client
import json
import re
import ssl
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .runner import ConvError, run

FORMATS = {"srt": "srt", "vtt": "vtt", "txt": "text"}
TIMEOUT = 4 * 3600
LANGUAGES = ["it", "en", "fr", "de", "es", "pt", "nl", "pl", "ro", "ru", "uk", "ar", "zh", "ja"]
CHUNK_SECONDS = 600  # l'audio piu' lungo di 15 minuti va a Whisper in pezzi di circa 10
_TIME = re.compile(r"(?:(\d+):)?(\d+):(\d+)[,.](\d+)")


async def _duration(path: Path) -> float:
    from .tools import ffprobe_duration
    return await ffprobe_duration(path)


def _seconds(stamp: str) -> float:
    m = _TIME.fullmatch(stamp.strip().split(" ")[0])
    if not m:
        raise ValueError(stamp)
    h, mi, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_cues(text: str) -> list[tuple[float, float, str]]:
    """Battute di un SRT o VTT: (inizio, fine, testo)."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                try:
                    cues.append((_seconds(a), _seconds(b), "\n".join(lines[i + 1:]).strip()))
                except ValueError:
                    pass
                break
    return [c for c in cues if c[2]]


def _stamp(t: float, sep: str) -> str:
    ms = round(max(t, 0) * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def format_cues(cues: list[tuple[float, float, str]], fmt: str) -> str:
    if fmt == "vtt":
        return "WEBVTT\n\n" + "\n\n".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{t}" for a, b, t in cues)
    return "\n\n".join(f"{n}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n{t}" for n, (a, b, t) in enumerate(cues, 1))


class Transcriber:
    """Convertitore audio/video -> testo; ``tool`` dell'arco: "Whisper"."""

    def __init__(self, url: str, model: str = "", api_key: str = ""):
        u = urlparse(url.strip().rstrip("/"))
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("WHISPER_URL deve essere un indirizzo http o https")
        path = u.path if u.path.endswith("/audio/transcriptions") else u.path + "/v1/audio/transcriptions"
        self.scheme, self.host, self.port, self.path = u.scheme, u.hostname, u.port, path
        self.model, self.api_key = model, api_key
        self.chunk = CHUNK_SECONDS
        self.__name__ = "transcribe"

    def __repr__(self) -> str:
        return f"Transcriber({self.scheme}://{self.host}{self.path})"

    async def __call__(self, job, inp: Path, out_ext: str, wd: Path) -> Path:
        from .tools import opts_of

        audio = wd / "audio.mp3"
        await run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(inp), "-vn", "-sn",
                   "-dn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(audio)],
                  timeout=TIMEOUT)
        if not audio.exists() or audio.stat().st_size == 0:
            raise ConvError("nessuna traccia audio da trascrivere")
        language = opts_of(job, out_ext).get("language", "")
        parts = await self.split(audio, wd)
        if len(parts) == 1:
            job.step = "Whisper: trascrizione"
            text = await asyncio.to_thread(self.post, audio, FORMATS[out_ext], language)
        else:
            # Audio lungo: un pezzo alla volta, cosi' il servizio non deve tenere in memoria ore di audio
            # (con speaches su CPU un'ora intera supera 2 GB). I sottotitoli vengono ricuciti spostando gli orari.
            fmt = "text" if out_ext == "txt" else "srt"
            texts, cues, offset = [], [], 0.0
            for i, part in enumerate(parts, 1):
                job.step, job.progress = f"Whisper: trascrizione (parte {i}/{len(parts)})", (i - 1) / len(parts)
                text = await asyncio.to_thread(self.post, part, fmt, language)
                if fmt == "text":
                    texts.append(text.strip())
                else:
                    cues += [(a + offset, b + offset, t) for a, b, t in parse_cues(text)]
                offset += await _duration(part)
            text = "\n\n".join(t for t in texts if t) if fmt == "text" else format_cues(cues, out_ext)
        if not text.strip():
            raise ConvError("Whisper non ha riconosciuto parole")
        out = wd / f"out.{out_ext}"
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return out

    async def split(self, audio: Path, wd: Path) -> list[Path]:
        """Divide l'audio in pezzi di circa ``chunk`` secondi, tagliando nei silenzi vicini al limite."""
        total = await _duration(audio)
        if total <= self.chunk * 1.5:
            return [audio]
        silences: list[float] = []

        def on_line(line: str) -> None:
            if m := re.search(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", line):
                silences.append(float(m[1]) - float(m[2]) / 2)

        await run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(audio), "-af", "silencedetect=n=-35dB:d=0.3",
                   "-f", "null", "-"], timeout=TIMEOUT, on_line=on_line)
        cuts, last = [], 0.0
        while total - last > self.chunk * 1.5:
            target = last + self.chunk
            near = [s for s in silences if target - self.chunk / 5 <= s <= target]
            last = max(near) if near else target
            cuts.append(last)
        folder = wd / "parts"
        folder.mkdir(exist_ok=True)
        for old in folder.glob("part*.mp3"):
            old.unlink()
        await run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio), "-f", "segment",
                   "-segment_times", ",".join(f"{c:.3f}" for c in cuts), "-reset_timestamps", "1", "-c", "copy",
                   str(folder / "part%03d.mp3")], timeout=TIMEOUT)
        parts = sorted(folder.glob("part*.mp3"))
        if not parts:
            raise ConvError("impossibile dividere l'audio in pezzi")
        return parts

    def post(self, audio: Path, fmt: str, language: str = "") -> str:
        """Manda l'audio al servizio (multipart, a blocchi) e restituisce il testo. Bloccante."""
        boundary = uuid.uuid4().hex
        fields = {"response_format": fmt, **({"model": self.model} if self.model else {}),
                  **({"language": language} if language else {})}
        head = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                        for k, v in fields.items())
        head += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.mp3"\r\n'
                 "Content-Type: audio/mpeg\r\n\r\n").encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}",
                   "Content-Length": str(len(head) + audio.stat().st_size + len(tail)), "Accept": "*/*"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        conn = (http.client.HTTPSConnection(self.host, self.port, timeout=TIMEOUT, context=ssl.create_default_context())
                if self.scheme == "https" else http.client.HTTPConnection(self.host, self.port, timeout=TIMEOUT))
        try:
            conn.putrequest("POST", self.path)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            conn.send(head)
            with audio.open("rb") as fh:
                while chunk := fh.read(1024 * 1024):
                    conn.send(chunk)
            conn.send(tail)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", "replace")
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
            raise ConvError("il servizio Whisper si e' interrotto durante la trascrizione (forse memoria insufficiente)") \
                from None
        except (OSError, http.client.HTTPException) as e:
            raise ConvError(f"servizio Whisper non raggiungibile ({e.__class__.__name__})") from None
        finally:
            conn.close()
        if resp.status != 200:
            raise ConvError(f"il servizio Whisper ha risposto {resp.status}: {body[:200]}")
        if (resp.getheader("content-type") or "").startswith("application/json"):
            try:  # alcuni servizi rispondono sempre in JSON: {"text": "..."}
                data = json.loads(body)
                body = data.get("text", body) if isinstance(data, dict) else body
            except ValueError:
                pass
        return body
