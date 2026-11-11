#!/usr/bin/env python3
"""Crea un PDF accanto ai .xopp e ai documenti Office degli utenti Nextcloud: nome.xopp -> nome.xopp.pdf.

Pensato per girare da cron come root sul server che ospita Nextcloud (serve Docker):

    */5 * * * *  python3 /percorso/pdf_watcher.py --data /percorso/nextcloud/data --nextcloud-container nextcloud

Ogni conversione usa un container senza rete, con la sola cartella dell'utente in sola lettura.
Non cancella mai nulla e non sovrascrive un PDF che non ha generato lui. Dopo ogni PDF chiede a Nextcloud
(occ files:scan) di registrarlo. Un file "PAUSE" nella cartella di stato sospende tutto.

Le opzioni si possono mettere anche in config.json nella cartella di stato (--base), con gli stessi nomi
delle opzioni (es. {"data": "/srv/nextcloud/data", "nextcloud_container": "nextcloud-app-*"}):
la riga di comando ha la precedenza.
"""
import argparse
import fcntl
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCKER = shutil.which("docker") or "/usr/bin/docker"
DEFAULTS = {
    "data": None,                  # cartella "data" di Nextcloud (contiene <utente>/files)
    "base": str(HERE),             # stato, log e lock
    "image": "pdf-watcher:1",      # immagine Docker con LibreOffice e Xournal++ (costruita se manca)
    "nextcloud_container": None,   # nome del container di Nextcloud, anche con * (es. "nextcloud-app-*")
    "telegram_config": None,       # JSON con bot_token e allowed_chat_ids, per gli avvisi
    "uid": 33,                     # utente proprietario dei file di Nextcloud (www-data)
    "settle": 300,                 # secondi senza modifiche prima di convertire
    "no_scan": False,
    "no_notify": False,
}
OFFICE = {".doc", ".docx", ".odt", ".rtf", ".ppt", ".pptx", ".odp"}
SOURCES = OFFICE | {".xopp"}
CONVERT_TIMEOUT = 600
MAX_ATTEMPTS = 3

# Riceve: tipo, file sorgente (relativo a /in). Lascia /out/out.pdf e stampa pagine attese e pagine ottenute.
INNER = r'''
set -u
kind=$1; src=$2
cd /in
if [ "$kind" = xopp ]; then
  ( cd "$(dirname "$src")" && timeout -k 10 "$LIMIT" nice -n 19 xvfb-run -a xournalpp --create-pdf=/out/out.pdf "$(basename "$src")" ) 2>&1 | tail -3
  echo "EXPECTED=$(gzip -dc "$src" | grep -ao '<page ' | wc -l)"
else
  timeout -k 10 "$LIMIT" nice -n 19 soffice -env:UserInstallation=file:///tmp/lo --headless --convert-to pdf --outdir /out/lo "$src" 2>&1 | tail -3
  mv /out/lo/*.pdf /out/out.pdf 2>/dev/null
  echo "EXPECTED=any"
fi
echo "PAGES=$(pdfinfo /out/out.pdf 2>/dev/null | awk '/^Pages:/{print $2}')"
'''


class Run:
    def __init__(self, cfg):
        self.data = Path(cfg["data"])
        self.base = Path(cfg["base"])
        self.image = cfg["image"]
        self.uid = int(cfg["uid"])
        self.settle = int(cfg["settle"])
        self.container_pattern = cfg["nextcloud_container"]
        self.telegram_config = Path(cfg["telegram_config"]) if cfg["telegram_config"] else None
        self.scan_enabled = not cfg["no_scan"]
        self.notify_enabled = not cfg["no_notify"] and self.telegram_config is not None
        self.state_path = self.base / "state.json"
        self.log_path = self.base / "logs" / "convert.log"
        self.state = {"files": {}}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())

    def log(self, text):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists() and self.log_path.stat().st_size > 5_000_000:
            os.replace(self.log_path, self.log_path.with_suffix(".log.1"))
        with self.log_path.open("a") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")

    def save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)

    def notify(self, text):
        """True se il messaggio e' partito: altrimenti l'avviso resta in sospeso per la run seguente."""
        self.log(f"AVVISO: {text}")
        if not self.notify_enabled:
            return True
        try:
            d = json.loads(self.telegram_config.read_text())
            for chat in d.get("allowed_chat_ids") or d.get("chat_ids") or []:
                data = urllib.parse.urlencode({"chat_id": str(chat), "text": text[:4000]}).encode()
                url = f"https://api.telegram.org/bot{d['bot_token'].strip()}/sendMessage"
                with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
                    r.read()
            return True
        except Exception as e:
            self.log(f"Telegram non raggiungibile ({type(e).__name__})")
            return False

    def ensure_image(self):
        ok = subprocess.run([DOCKER, "image", "inspect", self.image], capture_output=True).returncode == 0
        if ok:
            self.state.pop("build_alerted", None)
            return True
        self.log("immagine assente: la ricostruisco")
        try:
            context = self.base / "build" if (self.base / "build" / "Dockerfile").exists() else HERE
            r = subprocess.run([DOCKER, "build", "-q", "-t", self.image, str(context)],
                               capture_output=True, text=True, timeout=1500)
            if r.returncode == 0:
                return True
            detail = r.stderr[-300:]
        except subprocess.TimeoutExpired:
            detail = "timeout"
        self.log(f"build fallita: {detail}")
        if not self.state.get("build_alerted") and self.notify("Nextcloud PDF: costruzione dell'immagine fallita, conversioni ferme."):
            self.state["build_alerted"] = True
        return False

    def sources(self):
        for user_dir in sorted(self.data.iterdir()):
            files = user_dir / "files"
            if not files.is_dir():
                continue
            for root, dirs, names in os.walk(files):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in names:
                    if name[0] in ".~" or Path(name).suffix.lower() not in SOURCES:
                        continue
                    yield files, Path(root) / name

    def convert(self, files, src):
        """Ritorna (percorso del PDF nella cartella temporanea, dir temporanea) oppure solleva RuntimeError."""
        kind = "xopp" if src.suffix.lower() == ".xopp" else "office"
        tmp = Path(tempfile.mkdtemp(prefix="run-", dir=self.base / "tmp"))
        os.chown(tmp, self.uid, self.uid)
        name = f"pdf-watcher-{os.getpid()}"
        cmd = [DOCKER, "run", "--rm", "--name", name, "--network", "none", "--user", f"{self.uid}:{self.uid}",
               "--read-only", "--tmpfs", "/tmp:size=2g", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--memory", "4g", "--cpus", "4", "--pids-limit", "512",
               "-e", "HOME=/tmp", "-e", f"LIMIT={CONVERT_TIMEOUT}",
               "--mount", f"type=bind,src={files},dst=/in,readonly", "--mount", f"type=bind,src={tmp},dst=/out",
               self.image, "bash", "-c", INNER, "inner", kind, str(src.relative_to(files))]
        try:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=CONVERT_TIMEOUT + 60)
            except subprocess.TimeoutExpired:
                subprocess.run([DOCKER, "rm", "-f", name], capture_output=True)
                raise RuntimeError("tempo scaduto")
            out = r.stdout + r.stderr
            pages = re.search(r"^PAGES=(\d+)$", out, re.M)
            expected = re.search(r"^EXPECTED=(\S+)$", out, re.M)
            pdf = tmp / "out.pdf"
            if r.returncode != 0 or not pages or not pdf.exists() or int(pages.group(1)) == 0:
                reason = next((l for l in out.splitlines() if "could not be found" in l), None) \
                    or " ".join(out.split())[-200:]
                raise RuntimeError(reason)
            if expected and expected.group(1) != "any" and expected.group(1) != pages.group(1):
                raise RuntimeError(f"pagine diverse: {expected.group(1)} nel file, {pages.group(1)} nel PDF")
            return pdf, tmp
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def install(self, pdf, target):
        part = target.with_name(f".{target.name}.{os.getpid()}.part")   # Nextcloud ignora i .part
        shutil.copyfile(pdf, part)
        os.chown(part, self.uid, self.uid)
        os.chmod(part, 0o770)
        os.replace(part, target)

    def nextcloud_container(self):
        r = subprocess.run([DOCKER, "ps", "--format", "{{.Names}}"], capture_output=True, text=True)
        return next((n for n in r.stdout.split() if fnmatch.fnmatchcase(n, self.container_pattern)), None)

    def occ_scan(self, rel):
        """Fa registrare il file a Nextcloud; False se va ritentato alla prossima esecuzione."""
        if not self.scan_enabled or not self.container_pattern:
            return True
        nc = self.nextcloud_container()
        if not nc:
            self.log(f"container Nextcloud '{self.container_pattern}' non trovato: registro {rel} piu' tardi")
            return False
        r = subprocess.run([DOCKER, "exec", "-u", f"{self.uid}:{self.uid}", "-w", "/var/www/html", nc,
                            "php", "occ", "files:scan", "-q", f"--path=/{rel}"], capture_output=True, text=True)
        return r.returncode == 0

    def process(self, files, src):
        rel = str(src.relative_to(self.data))
        st = src.stat()
        sig = [st.st_mtime_ns, st.st_size]
        entry = self.state["files"].get(rel, {})
        target = src.with_name(src.name + ".pdf")
        target_rel = str(target.relative_to(self.data))

        if entry.get("sig") == sig and (entry.get("status") in ("ok", "conflict")
                                        or entry.get("attempts", 0) >= MAX_ATTEMPTS):
            return
        if time.time() - st.st_ctime < self.settle:     # rclone conserva mtime: conta ctime
            return
        if target.exists():
            tst = target.stat()
            if entry.get("output_sig") != [tst.st_mtime_ns, tst.st_size]:
                # Il PDF non e' nostro, o qualcuno l'ha sostituito: non si tocca.
                if entry.get("status") != "conflict" or entry.get("sig") != sig:
                    self.log(f"non sovrascrivo {target_rel}")
                    self.state["files"][rel] = {**entry, "sig": sig, "status": "conflict"}
                    self.save()
                return

        attempts = entry.get("attempts", 0) + 1 if entry.get("sig") == sig else 1
        started = time.time()
        try:
            pdf, tmp = self.convert(files, src)
        except RuntimeError as e:
            self.log(f"ERRORE {rel} (tentativo {attempts}/{MAX_ATTEMPTS}): {e}")
            alerted = entry.get("alerted") and entry.get("sig") == sig     # sorgente nuovo: nuovo avviso
            self.state["files"][rel] = {**entry, "sig": sig, "status": "failed", "attempts": attempts,
                                        "error": str(e)[:300], "alerted": bool(alerted)}
            self.save()
            return
        try:
            st2 = src.stat()
            if [st2.st_mtime_ns, st2.st_size] != sig:
                self.log(f"{rel} modificato durante la conversione: riprovo dopo")
                return
            self.install(pdf, target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        tst = target.stat()
        self.state["files"][rel] = {"sig": sig, "status": "ok", "attempts": 0, "output_sig": [tst.st_mtime_ns, tst.st_size],
                                    "scan_pending": target_rel}
        self.save()
        self.log(f"ok {target_rel} ({tst.st_size} byte, {time.time() - started:.0f}s)")

    def finish(self):
        for rel, entry in self.state["files"].items():
            pending = entry.get("scan_pending")
            if pending and self.occ_scan(pending):
                del entry["scan_pending"]
        failed = [(r, e) for r, e in self.state["files"].items()
                  if e.get("status") == "failed" and e.get("attempts", 0) >= MAX_ATTEMPTS and not e.get("alerted")]
        if failed:
            text = "Nextcloud PDF, conversione fallita:\n" + "\n".join(f"- {r}: {e.get('error', '')}" for r, e in failed)
            if self.notify(text):
                for _, e in failed:
                    e["alerted"] = True
        self.save()

    def main(self):
        if not self.ensure_image():
            self.save()
            return 1
        (self.base / "tmp").mkdir(exist_ok=True)
        for files, src in self.sources():
            try:
                self.process(files, src)
            except OSError as e:       # file sparito o rinominato mentre lavoravamo
                self.log(f"saltato {src}: {e}")
        self.finish()
        return 0


def load_config(argv=None):
    """Valori predefiniti, poi config.json nella cartella di stato, poi la riga di comando."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="cartella data di Nextcloud")
    p.add_argument("--base", help="cartella per stato, log e lock (predefinita: quella dello script)")
    p.add_argument("--image", help=f"immagine Docker (predefinita: {DEFAULTS['image']})")
    p.add_argument("--nextcloud-container", help="nome del container di Nextcloud, anche con *")
    p.add_argument("--telegram-config", help="JSON con bot_token e allowed_chat_ids per gli avvisi")
    p.add_argument("--uid", type=int, help="utente dei file di Nextcloud (predefinito 33, www-data)")
    p.add_argument("--settle", type=int, help="secondi senza modifiche prima di convertire (predefinito 300)")
    p.add_argument("--no-scan", action="store_true", default=None, help="non chiedere a Nextcloud di registrare i PDF")
    p.add_argument("--no-notify", action="store_true", default=None, help="niente avvisi Telegram")
    args = {k: v for k, v in vars(p.parse_args(argv)).items() if v is not None}
    base = Path(args.get("base", DEFAULTS["base"]))
    file_cfg = {}
    if (base / "config.json").exists():
        file_cfg = json.loads((base / "config.json").read_text())
        unknown = set(file_cfg) - set(DEFAULTS)
        if unknown:
            p.error(f"opzioni sconosciute in config.json: {', '.join(sorted(unknown))}")
    cfg = {**DEFAULTS, **file_cfg, **args, "base": str(base)}
    if not cfg["data"]:
        p.error("manca la cartella dei dati di Nextcloud (--data o \"data\" in config.json)")
    return cfg


def main(argv=None):
    cfg = load_config(argv)
    base = Path(cfg["base"])
    if (base / "PAUSE").exists():
        return 0
    lock = open(base / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # un'altra esecuzione e' ancora in corso
    return Run(cfg).main()


if __name__ == "__main__":
    sys.exit(main())
