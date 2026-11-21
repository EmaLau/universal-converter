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
import ssl
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .runner import ConvError, run

FORMATS = {"srt": "srt", "vtt": "vtt", "txt": "text"}
TIMEOUT = 4 * 3600
LANGUAGES = ["it", "en", "fr", "de", "es", "pt", "nl", "pl", "ro", "ru", "uk", "ar", "zh", "ja"]


class Transcriber:
    """Convertitore audio/video -> testo; ``tool`` dell'arco: "Whisper"."""

    def __init__(self, url: str, model: str = "", api_key: str = ""):
        u = urlparse(url.strip().rstrip("/"))
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("WHISPER_URL deve essere un indirizzo http o https")
        path = u.path if u.path.endswith("/audio/transcriptions") else u.path + "/v1/audio/transcriptions"
        self.scheme, self.host, self.port, self.path = u.scheme, u.hostname, u.port, path
        self.model, self.api_key = model, api_key
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
        job.step = "Whisper: trascrizione"
        text = await asyncio.to_thread(self.post, audio, FORMATS[out_ext], opts_of(job, out_ext).get("language", ""))
        if not text.strip():
            raise ConvError("Whisper non ha riconosciuto parole")
        out = wd / f"out.{out_ext}"
        out.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        return out

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
