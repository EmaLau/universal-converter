"""Impostazioni lette dalle variabili d'ambiente."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


def truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "si", "on")


def _pairs(text: str) -> set[tuple[str, str]]:
    """"heic>avif, pdf>epub" -> {("heic", "avif"), ("pdf", "epub")}."""
    out = set()
    for item in text.replace(";", ",").split(","):
        if ">" in item:
            src, dst = (p.strip().lower().lstrip(".") for p in item.split(">", 1))
            if src and dst:
                out.add((src, dst))
    return out


@dataclass(frozen=True)
class Settings:
    work_dir: Path = Path("/work")
    max_parallel: int = 2           # conversioni contemporanee
    max_queue: int = 200            # lavori in memoria (in coda + finiti) prima di rifiutarne altri
    retain_hours: float = 6.0       # dopo quante ore si cancellano i risultati
    max_upload_bytes: int = 20 * 1024**3
    max_output_bytes: int = 50 * 1024**3  # limite per ogni file scritto dai programmi di conversione
    disabled: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    data_dir: Path | None = None    # chiavi API e impostazioni dell'area admin (predefinita: <work_dir>/data)
    admin_password: str = ""        # password della pagina /admin (oppure file admin-password in data_dir)
    require_key: bool = False       # valore iniziale di "chiave obbligatoria per le API"
    admin_login: bool = True        # valore iniziale di "password per l'area admin"

    @property
    def jobs_dir(self) -> Path:
        return self.work_dir / "jobs"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir or self.work_dir / "data"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        work = Path(env.get("WORK_DIR", "/work"))
        disabled = _pairs(env.get("DISABLED_CONVERSIONS", ""))
        # Compatibilita': elenco [[src, dst], ...] scritto da selftest.py --write-disabled
        legacy = work / "disabled.json"
        if legacy.exists():
            try:
                disabled |= {(str(a), str(b)) for a, b in json.loads(legacy.read_text())}
            except (ValueError, TypeError):
                pass
        return cls(
            work_dir=work,
            max_parallel=max(1, int(env.get("MAX_PARALLEL", "2"))),
            max_queue=max(1, int(env.get("MAX_QUEUE", "200"))),
            retain_hours=float(env.get("RETAIN_HOURS", "6")),
            max_upload_bytes=int(float(env.get("MAX_UPLOAD_GB", "20")) * 1024**3),
            max_output_bytes=int(float(env.get("MAX_OUTPUT_GB", "50")) * 1024**3),
            disabled=frozenset(disabled),
            data_dir=Path(env["DATA_DIR"]) if env.get("DATA_DIR") else None,
            admin_password=env.get("CONVERTER_ADMIN_PASSWORD", ""),
            require_key=truthy(env.get("API_REQUIRE_KEY")),
            admin_login=truthy(env.get("CONVERTER_ADMIN_LOGIN", "true")),
        )
