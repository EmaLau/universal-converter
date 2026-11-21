"""Opzioni di conversione (facoltative) per i formati piu' usati.

Le opzioni dipendono dal programma che fa l'ultimo passaggio della conversione:
  ImageMagick  qualita' (JPG, WEBP, HEIC, AVIF, JP2), lato lungo massimo, metadati
  FFmpeg       taglio (inizio/fine), risoluzione e qualita' del video, bitrate e canali dell'audio, metadati
  Poppler      PDF in immagini: risoluzione (DPI) e pagine
Si mandano a ``POST /api/jobs`` nel campo ``options`` come JSON, per esempio ``{"quality": 80, "max_size": 1920}``.
``GET /api/options/{src}/{dst}`` dice quali opzioni valgono per una conversione.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from . import tools
from .formats import category

if TYPE_CHECKING:
    from .graph import Edge

LOSSY_IMAGES = {"jpg", "webp", "heic", "avif", "jp2"}
LOSSY_AUDIO = {"mp3", "m4a", "aac", "ogg", "opus", "wma", "ac3"}
CRF_VIDEO = {"mp4", "mov", "m4v", "mkv", "ts", "flv", "webm"}  # codec con qualita' costante (H.264 e VP9)
NO_AUDIO = {"gif"}
MAX_SECONDS = 24 * 3600


class OptionError(ValueError):
    """Opzione non valida: il messaggio va all'utente."""


# Definizioni: le stesse etichette compaiono nella pagina web (tradotte da i18n.js)
DEFS: dict[str, dict] = {
    "quality": {"type": "int", "label": "Qualità (1-100)", "min": 1, "max": 100, "placeholder": "90"},
    "max_size": {"type": "int", "label": "Lato lungo massimo (pixel)", "min": 16, "max": 20000, "placeholder": "1920"},
    "start": {"type": "time", "label": "Inizio (es. 0:30)", "placeholder": "0:00"},
    "end": {"type": "time", "label": "Fine (es. 1:45)", "placeholder": ""},
    "height": {"type": "select", "label": "Risoluzione massima",
               "choices": [["", "Originale"], ["2160", "4K (2160p)"], ["1440", "1440p"], ["1080", "1080p"],
                           ["720", "720p"], ["480", "480p"], ["360", "360p"]]},
    "video_quality": {"type": "select", "label": "Qualità del video",
                      "choices": [["", "Predefinita"], ["high", "Alta (file più grande)"], ["medium", "Media"],
                                  ["low", "Bassa (file più piccolo)"]]},
    "audio_bitrate": {"type": "select", "label": "Bitrate dell'audio",
                      "choices": [["", "Predefinito"], ["320", "320 kbps"], ["256", "256 kbps"], ["192", "192 kbps"],
                                  ["128", "128 kbps"], ["96", "96 kbps"], ["64", "64 kbps"]]},
    "mono": {"type": "bool", "label": "Audio mono (un solo canale)"},
    "dpi": {"type": "select", "label": "Risoluzione delle pagine",
            "choices": [["", "150 DPI (predefinita)"], ["72", "72 DPI (schermo)"], ["300", "300 DPI (stampa)"]]},
    "pages": {"type": "text", "label": "Pagine (es. 2 oppure 3-5)", "placeholder": "tutte"},
    "strip": {"type": "bool", "label": "Togli i metadati (data, posizione GPS, fotocamera)"},
}
CRF = {"libx264": {"high": "18", "medium": "23", "low": "28"}, "libvpx-vp9": {"high": "26", "medium": "33", "low": "40"}}


def applicable(plan: list[Edge] | None, target: str) -> list[str]:
    """Nomi delle opzioni che valgono per una conversione, nell'ordine in cui vanno mostrate."""
    if not plan:
        return []
    last = plan[-1]
    if last.fn is tools.imagemagick:
        return (["quality"] if target in LOSSY_IMAGES else []) + ["max_size", "strip"]
    if last.fn is tools.ffmpeg:
        out = ["start", "end"]
        if category(target) == "Video" or target == "gif":
            out.append("height")
            if target in CRF_VIDEO:
                out.append("video_quality")
            if target not in NO_AUDIO:
                out.append("audio_bitrate")
        else:  # audio
            if target in LOSSY_AUDIO:
                out.append("audio_bitrate")
            out.append("mono")
        return out + ["strip"]
    if last.fn is tools.pdf_to_images and len(plan) == 1:
        return ["dpi", "pages"]
    return []


def definitions(names: list[str]) -> list[dict]:
    return [{"name": n, **DEFS[n]} for n in names]


def parse_time(value: str) -> float:
    """"90", "1:30", "01:02:03.5" -> secondi."""
    v = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?|\d+:\d{1,2}(\.\d+)?|\d+:\d{1,2}:\d{1,2}(\.\d+)?", v):
        raise ValueError
    secs = 0.0
    for part in v.split(":"):
        secs = secs * 60 + float(part)
    if secs > MAX_SECONDS:
        raise ValueError
    return secs


def parse(raw: str | dict | None, plan: list[Edge] | None, target: str) -> dict:
    """Controlla le opzioni ricevute (JSON o dizionario) e restituisce quelle pulite; solleva OptionError."""
    if not raw:
        return {}
    if isinstance(raw, str):
        if len(raw) > 4000:
            raise OptionError("options troppo lungo")
        try:
            raw = json.loads(raw)
        except ValueError:
            raise OptionError("options deve essere un oggetto JSON") from None
    if not isinstance(raw, dict):
        raise OptionError("options deve essere un oggetto JSON")
    allowed = applicable(plan, target)
    out: dict = {}
    for name, value in raw.items():
        if value is None or value == "" or value is False:
            continue
        if name not in DEFS:
            raise OptionError(f"opzione sconosciuta: {name}")
        if name not in allowed:
            raise OptionError(f"opzione non disponibile per questa conversione: {name}")
        d = DEFS[name]
        try:
            if d["type"] == "int":
                n = int(value)
                if isinstance(value, float) and value != n or not d["min"] <= n <= d["max"]:
                    raise ValueError
                out[name] = n
            elif d["type"] == "bool":
                if value not in (True, "true", "1", 1, "on"):
                    raise ValueError
                out[name] = True
            elif d["type"] == "select":
                if str(value) not in {c[0] for c in d["choices"] if c[0]}:
                    raise ValueError
                out[name] = str(value)
            elif d["type"] == "time":
                out[name] = parse_time(str(value))
            elif name == "pages":
                m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d*)\s*)?", str(value))
                if not m or int(m.group(1)) < 1 or (m.group(2) and int(m.group(2)) < int(m.group(1))):
                    raise ValueError
                first = int(m.group(1))
                last = first if m.group(2) is None else (int(m.group(2)) if m.group(2) else 0)  # 0 = fino alla fine
                out[name] = [first, last]
        except (TypeError, ValueError):
            raise OptionError(f"valore non valido per '{d['label']}': {value}") from None
    if "start" in out and "end" in out and out["end"] <= out["start"]:
        raise OptionError("la fine deve venire dopo l'inizio")
    if out.get("start") == 0:
        del out["start"]
    return out


# ------------------------------------------------------------------------- argomenti per i programmi

def magick_args(opts: dict, out_ext: str, final: bool) -> list[str]:
    """Argomenti aggiunti a ImageMagick: lato lungo massimo e metadati; la qualita' la sceglie tools.imagemagick."""
    args = []
    if opts.get("max_size"):
        n = opts["max_size"]
        args += ["-resize", f"{n}x{n}>"]
    if opts.get("strip") and final:
        args.append("-strip")
    return args


def ffmpeg_input_args(opts: dict) -> list[str]:
    """Taglio: -ss prima di -i (salto veloce), -t per la durata."""
    args = []
    if opts.get("start"):
        args += ["-ss", f"{opts['start']:g}"]
    if opts.get("end"):
        args += ["-t", f"{opts['end'] - opts.get('start', 0):g}"]
    return args


def reencode_needed(opts: dict) -> bool:
    """Con queste opzioni la copia senza ricodifica non basta."""
    return any(opts.get(k) for k in ("start", "end", "height", "video_quality", "audio_bitrate", "mono"))


def ffmpeg_output_args(args: list[str], opts: dict, out_ext: str) -> list[str]:
    """Adatta gli argomenti di codifica di tools.ffmpeg alle opzioni scelte."""
    args = list(args)
    if not opts:
        return args
    h = opts.get("height")
    if h:
        scale = f"scale=-2:'min({h},ih)'"
        if "-filter_complex" in args:  # GIF: sostituisce la scala predefinita (640 px di larghezza)
            i = args.index("-filter_complex") + 1
            args[i] = re.sub(r"scale='min\(640,iw\)':-2", f"scale=-2:'min({h},ih)'", args[i])
        elif "-vf" in args:
            i = args.index("-vf") + 1
            args[i] = scale
        else:
            args += ["-vf", scale]
    q = opts.get("video_quality")
    if q and "-crf" in args:
        codec = args[args.index("-c:v") + 1] if "-c:v" in args else ""
        if codec in CRF:
            args[args.index("-crf") + 1] = CRF[codec][q]
    br = opts.get("audio_bitrate")
    if br and "-c:a" in args:
        for flag in ("-q:a", "-b:a"):
            while flag in args:
                i = args.index(flag)
                del args[i:i + 2]
        args += ["-b:a", f"{br}k"]
    if opts.get("mono"):
        args += ["-ac", "1"]
    return args
