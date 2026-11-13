---
title: Universal Converter
pagetitle: Universal Converter — Documentation
lang: en
---

> 🇮🇹 An Italian version of this document, [`documentazione.md`](documentazione.md), is the one served by every instance at `/docs`. The user interface is in Italian: Italian labels are quoted below with their English meaning.

# Overview

Universal Converter is a **self-hosted** file converter: you install it on your computer or server, and it converts documents, spreadsheets, presentations, drawings, images, audio, video, subtitles, ebooks, data, fonts and archives. It is meant as a private alternative to services such as iLovePDF or CloudConvert: files never leave your network and are deleted automatically after a few hours.

The project has three independent parts:

| Part | Folder | Purpose |
|---|---|---|
| **Server** | `server/` | Web page and JSON API. It is the core of the project and works on its own. |
| **Nextcloud app** | `nextcloud-app/` | Optional: adds **Converti in…** ("Convert to…") to the Nextcloud file menu and uses the server to convert. |
| **Automatic PDFs** | `pdf-watcher/` | Optional: creates a PDF next to Xournal++ notes and Office documents of Nextcloud users. |

## By the numbers

- about **200 input extensions**;
- more than **3,000 source → target combinations**;
- **15 conversion programs** (LibreOffice, FFmpeg, ImageMagick, Pandoc, Calibre, Poppler, Ghostscript, librsvg, LibRaw, img2pdf, pdf2docx, libarchive, 7-Zip, Xournal++, fontTools), plus data conversions written in Python;
- a self-test that actually runs every combination for its sample files (more than 300 conversions).

# Supported formats

Formats are grouped into categories. For each file, the web page and the Nextcloud app show only the targets that make sense.

| Category | Extensions |
|---|---|
| Document | PDF, DOCX, ODT, DOC, RTF, TXT, HTML, MD, TEX, RST, AsciiDoc (ADOC), Typst (TYP), Org, Pages, WordPerfect (WPD), Works (WPS), FODT, AbiWord (ABW), StarOffice (SXW), Lotus Word Pro (LWP), Hangul (HWP), Jupyter (IPYNB), Textile, DocBook (DBK), MediaWiki (WIKI), Texinfo (TEXI), OPML, txt2tags (T2T), Xournal++ (XOPP) |
| Spreadsheet | XLSX, ODS, XLS, CSV, TSV, Numbers, FODS, XLSB, StarOffice (SXC), DIF, SYLK (SLK), dBase (DBF), Lotus (WK1) |
| Presentation | PPTX, ODP, PPT, Keynote (KEY), FODP, StarOffice (SXI) |
| Drawing | SVG, EPS, PS, Visio (VSD, VSDX), ODG, Publisher (PUB), CorelDRAW (CDR), WMF, EMF |
| Image | JPG, PNG, WEBP, HEIC, AVIF, GIF, TIFF, BMP, ICO, JPEG 2000 (JP2), QOI, TGA, PSD, PPM, PBM, PGM, PNM, PCX, DDS, HDR, GIMP (XCF), XPM, APNG and camera RAW files (DNG, CR2, CR3, NEF, ARW, RAF, ORF, RW2) |
| Audio | MP3, M4A, WAV, FLAC, OGG, OPUS, AAC, AIFF, WMA, AC3, MKA, AMR, DTS, APE, WavPack (WV), CAF, AU, MP2, TTA |
| Video | MP4, MKV, MOV, WEBM, AVI, WMV, FLV, M4V, 3GP, MTS, MPG, TS, OGV, VOB, MXF, ASF, RM, RMVB, F4V, DIVX, DV |
| Subtitles | SRT, VTT, ASS, SSA |
| Ebook | EPUB, MOBI, AZW3, AZW, FB2, LIT, PDB, HTMLZ, TXTZ, LRF, comics (CBZ, CBR, CB7), CHM, SNB, TCR, PML |
| Data | JSON, YAML, TOML |
| Font | TTF, OTF, WOFF, WOFF2 |
| Archive | ZIP, 7Z, TAR.GZ, TAR.XZ, TAR.BZ2, TAR.ZST, TAR, RAR, ISO, CAB, CPIO, LHA |

The most common synonyms are recognised too: `.jpeg` and `.jfif` as JPG, `.tif` as TIFF, `.yml` as YAML, `.tgz` as TAR.GZ, `.docm` as DOCX, and so on.

The complete, always up-to-date list of combinations is on the web page, under **Tutti i formati supportati** ("All supported formats"), or from the API at `GET /api/formats`.

## Some examples

| From | To | How |
|---|---|---|
| Word, ODT, RTF, Pages | PDF | LibreOffice |
| PDF | Word | pdf2docx (only from an original PDF, not from one just generated) |
| PDF | JPG or PNG | Poppler, one image per page; with several pages you get a ZIP |
| PDF | SVG | Poppler, one vector SVG per page |
| HEIC (iPhone photos) | JPG | ImageMagick |
| Video | MP4 | FFmpeg: if the codecs are already compatible, the streams are copied without re-encoding, so it takes seconds |
| Video | GIF | FFmpeg, first 60 seconds, 12 frames per second, at most 640 px wide |
| Markdown | PowerPoint | Pandoc: one slide per heading |
| Markdown | PDF | Pandoc (MD → DOCX) + LibreOffice (DOCX → PDF) |
| JSON | Excel | Python (JSON → CSV) + LibreOffice (CSV → XLSX) |
| Excel | JSON | LibreOffice (XLSX → CSV) + Python (CSV → JSON) |
| SRT | VTT | FFmpeg |
| TTF, OTF | WOFF2 | fontTools |
| RAR, 7Z, ISO | ZIP | libarchive |

# Installation

## With Docker Compose (recommended)

You need Docker with the Compose plugin.

```bash
git clone https://github.com/EmaLau/universal-converter.git
cd universal-converter
cp .env.example .env        # optional
docker compose up -d --build
```

Then open <http://localhost:8080>.

The first build downloads LibreOffice, FFmpeg, Calibre and the other programs: about 500 MB to download and a final image of about 3.5 GB. Depending on your connection it takes 5-20 minutes. Later builds are much faster: the programs live in a separate image layer that stays cached, and if you only change the code the build takes a few seconds.

To check that everything works:

```bash
docker compose exec converter python3 /app/selftest.py
```

## With Docker, without Compose

```bash
docker build -t universal-converter server/
docker run -d --name universal-converter -p 127.0.0.1:8080:8080 \
  -v converter-work:/work universal-converter
```

## Without Docker (development)

The server is a regular Python package (FastAPI). To work on the code:

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
WORK_DIR=/tmp/converter .venv/bin/uvicorn --factory converter.app:create_app --reload
```

Without the conversion programs installed on your computer, the page and the API work, but conversions fail. Use Docker for real conversions.

## Architectures

The image is based on Debian 13 (trixie) and runs on both x86-64 (PCs, NAS, servers) and ARM64 (Apple Silicon Macs, Raspberry Pi 4/5).

# Configuration

Settings go in `.env`, in the project's root folder (start from `.env.example`). Docker Compose passes them to the container as environment variables.

| Variable | Default | Description |
|---|---|---|
| `CONVERTER_BIND` | `127.0.0.1` | Address the service is published on. `127.0.0.1` makes it reachable only from the machine itself, `0.0.0.0` from the whole network. |
| `CONVERTER_PORT` | `8080` | Published port. |
| `MAX_PARALLEL` | `2` | Conversions run at the same time; the others wait in the queue. Each LibreOffice or FFmpeg process uses a lot of CPU and memory: raise it only if the server has the resources. |
| `MAX_QUEUE` | `200` | Jobs kept in memory (queued + running + finished and not yet deleted). Beyond this number the server answers `503` ("too many jobs"). |
| `RETAIN_HOURS` | `6` | Hours after which the result of a finished job is deleted. |
| `MAX_UPLOAD_GB` | `20` | Maximum size of an uploaded file. |
| `MAX_OUTPUT_GB` | `50` | Maximum size of **each file** written by a program during a conversion. If a program hangs and keeps writing, it is stopped when it reaches the limit and the job ends with a clear error, before the disk fills up. |
| `DISABLED_CONVERSIONS` | empty | Conversions to hide, comma-separated. Example: `heic>avif,pdf>epub`. |
| `CONVERTER_ADMIN_PASSWORD` | empty | Password for the `/admin` page that manages [API keys](#api-keys). It can also be written in `/work/data/admin-password`. Without a password the admin area stays disabled. |
| `API_REQUIRE_KEY` | `false` | Initial value of the *Key required for the API* switch; afterwards the value saved on the `/admin` page wins. |
| `CONVERTER_ADMIN_LOGIN` | `true` | Initial value of the *Password to enter this page* switch. |
| `DATA_DIR` | `/work/data` | Folder holding the API keys and admin settings. |
| `CONVERTER_CPUS` | `4` | Maximum CPUs for the container. |
| `CONVERTER_MEMORY` | `4G` | Maximum memory for the container. |
| `CONVERTER_UID`, `CONVERTER_GID` | `1000` | User and group that run the service inside the container. They also own the working files: set them if you mount a host folder instead of the volume. |
| `TZ` | `Europe/Rome` | Time zone. |

After changing `.env`: `docker compose up -d`.

## Working directory

All temporary files live in `/work` inside the container (with Docker Compose it is the `converter-work` volume):

| Path | Contents |
|---|---|
| `/work/jobs/<id>/` | One job: uploaded file, intermediate steps, result. |
| `/work/tmp/` | Programs' temporary files. |
| `/work/home/` | Programs' profiles and caches (Calibre, Xournal++…). |
| `/work/disabled.json` | Disabled conversions (optional, see [Maintenance](#maintenance)). |
| `/work/data/` | API keys (SHA-256 fingerprint only), admin settings, the cookie signing secret and, if present, the `admin-password` file. It is **not** emptied at startup. |

The `jobs` folder is emptied at startup: jobs live only in memory, so those from a previous run are no longer reachable.

# Using the web page

The main page shows a grid of ready-made **tools** ("Word in PDF", "HEIC in JPG", "JSON in Excel"…), which can be filtered by category, plus the **Qualsiasi formato** ("Any format") tool.

1. Pick a tool, or **Qualsiasi formato**.
2. Select one or more files, or drag them onto the page.
3. Choose the target format for each file. With several files, the **Converti tutti in** ("Convert all to") menu at the bottom sets the same format for all of them.
4. Press **Converti** ("Convert"). Each file shows the upload, its position in the queue, the current step and, for audio, video and ebooks, the percentage.
5. When a file is ready, **Scarica** ("Download") appears; with several files ready, also **Scarica tutti** ("Download all").

Below the grid, **Tutti i formati supportati** ("All supported formats") lists every possible target for each source format.

Notes:

- Files larger than the limit (`MAX_UPLOAD_GB`) are flagged immediately, without uploading them.
- If a conversion fails, the message explains why, and the **Riprova** ("Retry") button puts it back in the queue.
- Results can be downloaded for `RETAIN_HOURS` hours, then they are deleted.
- The page follows the operating system's light or dark theme.

# API

The API uses JSON and is the same one used by the web page and the Nextcloud app. Interactive documentation, where calls can be tried out, is at `/apidocs`.

## API keys

Keys are created on the `/admin` page, modelled on Gokapi. To enable it set `CONVERTER_ADMIN_PASSWORD` (or the `/work/data/admin-password` file) and restart.

- Each key has a name and permissions:

  | Permission | Calls |
  |---|---|
  | `formats` | `GET /api/formats`, `GET /api/plan/{src}/{dst}` |
  | `convert` | `POST /api/jobs` |
  | `jobs` | `GET /api/jobs/{id}`, `GET /api/jobs/{id}/download`, `DELETE /api/jobs/{id}` |

  A full client, such as the Nextcloud app or Plico, needs all three.
- The full key is shown **only once**, when it is created: the server keeps only its SHA-256 fingerprint. The page shows the start of the key, when it was created and when it was last used; permissions can be changed and keys revoked.
- Scripts send the key in the `apikey` header. It is checked **before** the file is received: `401` for a wrong or revoked key, `403` for a missing permission.
- The web page needs no key: opening it gives a signed session cookie.
- The **Key required for the API** switch (off by default) rejects with `401` calls without a key made outside the web page. When off, calls without a key are accepted as before, while calls with a key are limited to its permissions.
- The **Password to enter this page** switch can be turned off, but then anyone who reaches the service can manage the keys.
- Admin area protections: signed cookie valid for 12 hours (`SameSite=Strict`), 5 wrong attempts per IP address in 10 minutes then `429`; changes require the `X-Requested-With` header.

```bash
curl -H "apikey: uconv_..." -F file=@report.docx -F target=pdf http://localhost:8080/api/jobs
```

## Summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Service status |
| `GET` | `/api/formats` | Supported formats and combinations |
| `GET` | `/api/plan/{src}/{dst}` | Planned steps for a conversion |
| `POST` | `/api/jobs` | Create a job by uploading a file |
| `GET` | `/api/jobs/{id}` | Job status |
| `GET` | `/api/jobs/{id}/download` | Download the result |
| `DELETE` | `/api/jobs/{id}` | Delete a job and its files immediately |
| `GET` | `/docs` | This documentation (Italian version) |
| `GET` | `/apidocs` | Interactive API documentation |
| `GET` | `/admin` | API keys |

## `GET /healthz`

```json
{"ok": true, "version": "2.0.0", "jobs": 3, "running": 1, "queued": 0}
```

Also used by the Docker healthcheck. It never requires a key.

## `GET /api/formats`

```json
{
  "inputs": {"docx": ["pdf", "odt", "doc", "rtf", "txt", "html", "md", "..."], "...": []},
  "categories": {"pdf": "Documento", "mp3": "Audio", "...": "..."},
  "tools": ["Calibre", "FFmpeg", "ImageMagick", "LibreOffice", "..."],
  "retain_hours": 6.0,
  "max_upload_bytes": 21474836480
}
```

`inputs` also contains the synonyms (`jpeg`, `yml`…), with the same targets as the main format. Category names are returned in Italian (`Documento` = Document, `Foglio di calcolo` = Spreadsheet, and so on).

## `GET /api/plan/{src}/{dst}`

```bash
curl http://localhost:8080/api/plan/json/xlsx
```

```json
[{"tool": "Python", "from": "json", "to": "csv"},
 {"tool": "LibreOffice", "from": "csv", "to": "xlsx"}]
```

Returns `404` if the conversion is not supported.

## `POST /api/jobs`

A `multipart/form-data` request with these fields:

| Field | Required | Description |
|---|---|---|
| `file` | yes | The file to convert. The source format is taken from the file name's extension. |
| `target` | yes | Target extension, for example `pdf`. |
| `meta` | no | Free text (at most 2,000 characters) returned in the job status: useful for integrations. |

Returns `201` with the job status (see below). Errors:

| Code | When |
|---|---|
| `400` | Conversion not supported, or empty file |
| `413` | File larger than `MAX_UPLOAD_GB` |
| `503` | Too many jobs in memory (`MAX_QUEUE`): try again shortly |

Errors always have the form `{"detail": "message"}`. Messages are in Italian, meant to be shown to the user.

## `GET /api/jobs/{id}`

```json
{
  "id": "4f6c0e1d2b9a4c8e9f0a1b2c3d4e5f60",
  "filename": "report.docx",
  "target": "pdf",
  "state": "running",
  "progress": null,
  "step": "LibreOffice: DOCX → PDF",
  "error": "",
  "meta": "",
  "created": 1762870000.12,
  "finished": null
}
```

| Field | Meaning |
|---|---|
| `state` | `queued`, `running`, `done`, `error` |
| `position` | Only when `queued`: position in the queue, starting from 1 |
| `progress` | From 0 to 1 when the program reports progress (FFmpeg, Calibre, PDF → SVG), otherwise `null` |
| `step` | Current step, with the step number when there is more than one |
| `error` | When `error`: the reason, suitable for showing to the user |
| `out_name`, `size` | When `done`: name of the resulting file and size in bytes |

Returns `404` if the job does not exist: never created, already deleted, expired, or the server was restarted.

## `GET /api/jobs/{id}/download`

Returns the file with the right name (`Content-Disposition`), accented characters included. Returns `409` if the job has not finished yet.

The result's name is the original file's name with the new extension: `Final report.docx` → `Final report.pdf`. If the result contains several files, for example the pages of a PDF converted to images, you get a ZIP.

## `DELETE /api/jobs/{id}`

Deletes the job and its files immediately. If it is still running, it is stopped. Returns `{"ok": true}`.

## Complete example with curl

```bash
id=$(curl -s -F file=@report.docx -F target=pdf http://localhost:8080/api/jobs | jq -r .id)

while [ "$(curl -s http://localhost:8080/api/jobs/$id | jq -r .state)" != "done" ]; do sleep 1; done

curl -OJ http://localhost:8080/api/jobs/$id/download
curl -X DELETE http://localhost:8080/api/jobs/$id
```

## Example in Python

```python
import time
import requests

API = "http://localhost:8080"

with open("photo.heic", "rb") as fh:
    job = requests.post(f"{API}/api/jobs", files={"file": fh}, data={"target": "jpg"}).json()

while (st := requests.get(f"{API}/api/jobs/{job['id']}").json())["state"] in ("queued", "running"):
    time.sleep(1)

if st["state"] == "error":
    raise SystemExit(st["error"])

with open(st["out_name"], "wb") as out:
    out.write(requests.get(f"{API}/api/jobs/{job['id']}/download").content)
requests.delete(f"{API}/api/jobs/{job['id']}")
```

# How it works

## The conversion graph

Each conversion program is described by **edges** "extension → extension". For example, LibreOffice has a DOCX → PDF edge, Pandoc an MD → DOCX edge, Python a JSON → CSV edge.

At startup, for each source format the server uses **Dijkstra's algorithm** to compute the cheapest path to every other format, with at most **3 steps**. So, without writing every combination by hand:

- Markdown → PDF becomes Pandoc (MD → DOCX) + LibreOffice (DOCX → PDF);
- CorelDRAW → PNG becomes LibreOffice (CDR → PDF) + Poppler (PDF → PNG);
- YAML → Excel becomes Python (YAML → CSV) + LibreOffice (CSV → XLSX).

Each edge has a **cost**, 1 by default. Some cost more, so that better alternatives are preferred when they exist: Calibre (1.2) and Pandoc from DOCX/ODT/EPUB (1.5).

Two special properties:

- **source only** (`source_only`): the edge can only be the first step. PDF → Word with pdf2docx works well on a real PDF, but would make no sense after a DOCX → PDF. The same applies to Markdown → PowerPoint and to WOFF → TTF/OTF.
- **final** (`final_only`): the edge produces several files (the pages of a PDF as images or SVGs), so nothing can come after it.

## Sensible combinations

Technically you could turn an Excel sheet into an MP3 (Excel → PDF → image → video…), but nobody needs that. A set of rules removes such combinations from the menus:

- audio only to audio; video only to video, audio and GIF;
- subtitles and fonts only to the same category;
- data (JSON, YAML, TOML) only to data and spreadsheets, and vice versa;
- archives only to archives;
- images to images or PDF (plus GIF/APNG → video);
- spreadsheets to documents only as PDF, HTML, TXT or Markdown;
- presentations to documents only as PDF;
- drawings to images, drawings or PDF;
- presentations can be created from a document only if it is written in a markup language (Markdown, reStructuredText, Org, HTML, Textile).

## Jobs

1. **Upload.** The file is written to `/work/jobs/<id>/` in 4 MB chunks, checking the maximum size. The name is stripped of paths and non-printable characters.
2. **Queue.** The job waits until one of the `MAX_PARALLEL` slots is free.
3. **Steps.** Each step works in its own folder (`step1`, `step2`…). The output of one step becomes the input of the next, with the correct extension. An empty file counts as an error.
4. **End.** The uploaded file is deleted immediately; the result stays available for `RETAIN_HOURS` hours.
5. **Cleanup.** Every 10 minutes the server deletes jobs that finished more than `RETAIN_HOURS` hours ago.

## Running the programs

- Programs are started **without a shell**, with separate arguments: a file name can never become a command.
- Each program has a **timeout**: 10 minutes for LibreOffice, 30 for pdf2docx and Calibre, 4 hours for FFmpeg. When it expires, the program is terminated together with all its child processes.
- Each file written by a program is limited to `MAX_OUTPUT_GB`.
- On error, the user sees the last lines of the program's output.
- LibreOffice uses a separate profile for each job, so several conversions can run in parallel. If it hangs at startup, which rarely happens, it is retried once with a clean profile.

## Quality and speed choices

- **Video**: to MP4, MOV, M4V, TS and FLV, if the codecs are already H.264 (or HEVC where the container allows it) with AAC or MP3 audio, the streams are **copied without re-encoding**. To MKV, copying is always tried first. Only when that is not possible is the video re-encoded: H.264 CRF 21 with AAC, VP9 for WEBM, Theora for OGV, WMV2, MPEG-2.
- **Images**: quality 90 for JPG, WEBP, HEIC and AVIF. Automatic rotation from EXIF data. White background instead of transparency for JPG and BMP. ICO icons contain every size from 16 to 256 px.
- **CSV**: the separator (comma, semicolon or tab) is detected automatically.
- **Text from DOCX/ODT**: Pandoc is used instead of LibreOffice, because of a known issue (see [Known issues](#known-issues)).
- **Data → CSV**: an object with a single list (`{"people": [...]}`) becomes a table with one row per item. Columns are the union of the keys; nested values become JSON text in the cell.
- **Fonts**: from WOFF/WOFF2 you go back to the right format based on the font's outlines, TrueType → TTF and PostScript/CFF → OTF. If you pick the wrong one, the error explains why.

# Nextcloud integration

The `nextcloud-app/` app (id `convertitore`, Nextcloud 30-36) adds a **Converti in…** ("Convert to…") submenu to every file's menu, listing the formats possible for that file. It also works on several selected files: in that case it shows only the formats common to all of them.

## Installation

1. Copy the `nextcloud-app` folder to `custom_apps/convertitore` in your Nextcloud installation, owned by the web server user (usually `www-data`, UID 33):

   ```bash
   cp -r nextcloud-app /var/www/html/custom_apps/convertitore
   chown -R www-data:www-data /var/www/html/custom_apps/convertitore
   ```

2. Enable it and set the converter's address. It must be reachable **from the Nextcloud server**, not from the browser:

   ```bash
   occ app:enable convertitore
   occ config:app:set convertitore converter_url --value=http://192.0.2.10:8080
   ```

   With Docker, run `occ` like this: `docker exec -u 33 <nextcloud-container> php occ ...`.

3. If the converter requires a key, create one on the `/admin` page with the `formats`, `convert` and `jobs` permissions and give it to the app:

   ```bash
   occ config:app:set convertitore converter_api_key --value=uconv_...
   ```

Until `converter_url` is set, the app shows no menu entry. Private addresses (192.168.x.x, 10.x.x.x…) are allowed: the app explicitly authorises them in Nextcloud's HTTP client.

## How it works

1. The user chooses **Converti in ▸ PDF**. The browser calls the app, which sends the file to the converter.
2. The browser polls the status every 1.5-5 seconds and shows a notification with queue, step and percentage.
3. When the converter is done, the result is saved **next to the original**, with a free name: `report.pdf`, then `report (2).pdf`… If the folder is read-only (for example a share), the file goes to the user's root folder and the notification says so.
4. The new file appears immediately in the open folder.

Whoever gets there first does the saving: the browser or a **Nextcloud background job**. So the file arrives even if the user closes the page. Nextcloud's cron must be active (Settings → Administration → Basic settings → Background jobs → Cron).

The list of formats is requested from the converter and cached for one hour; if the converter does not answer, the app retries after one minute. After adding formats to the server, clear the cache or wait an hour to see them.

## Common problems

| Symptom | Likely cause |
|---|---|
| No "Converti in" entry | `converter_url` is not set, or the converter is not reachable from Nextcloud. Check the Nextcloud log for `Convertitore non raggiungibile` ("converter unreachable"). |
| The entry is missing only for some files | The format is not supported, or the file is not readable by the user. |
| "Conversione sconosciuta o scaduta" ("unknown or expired conversion") | More than 48 hours have passed, or the Nextcloud cache was cleared. |
| "Il convertitore ha perso il lavoro" ("the converter lost the job") | The converter was restarted during the conversion: try again. |

# Automatic PDFs for Nextcloud

`pdf-watcher/pdf_watcher.py` automatically creates a PDF next to every `.xopp` (Xournal++), `.doc`, `.docx`, `.odt`, `.rtf`, `.ppt`, `.pptx` and `.odp` file of Nextcloud users, named `file.extension.pdf` (for example `Notes.xopp` → `Notes.xopp.pdf`). It is handy for reading notes on a phone or sharing them with people who do not have the right programs.

It is independent of the server: it runs from cron, as root, on the machine that holds the Nextcloud data, and it uses Docker.

## How it works

On every run the script:

1. checks that the conversion Docker image exists and, if not, builds it from the `Dockerfile` in its folder;
2. walks through the users' files in `<data>/<user>/files`, skipping hidden files and folders;
3. converts every new or modified file that has been **unchanged for at least 5 minutes** (so it does not create a PDF at every save);
4. checks the result: it must have at least one page, and for Xournal++ the same number of pages as the original;
5. copies the PDF next to the original with the right owner, going through a temporary `.part` file that Nextcloud ignores;
6. asks Nextcloud to register the new file (`occ files:scan`);
7. after 3 failed attempts on the same file, sends an alert if Telegram is configured.

Guarantees:

- **it never deletes anything**;
- **it never overwrites a PDF it did not create**: if it finds a PDF with that name made by someone else, or modified afterwards, it leaves it alone;
- if the original file changes during the conversion, it gives up and tries again next time;
- every conversion runs in a container **without network**, read-only, unprivileged, with limits on memory (4 GB), CPU (4), processes (512) and time (10 minutes); it sees only the user's folder, and that one read-only too;
- only one run at a time (`.lock` file); a `PAUSE` file in the state folder suspends everything.

## Options

| Option | Key in `config.json` | Default | Description |
|---|---|---|---|
| `--data` | `data` | — (required) | Nextcloud `data` folder |
| `--base` | — | script folder | Where to keep state, logs, lock and `config.json` |
| `--image` | `image` | `pdf-watcher:1` | Docker image name |
| `--nextcloud-container` | `nextcloud_container` | — | Name of the Nextcloud container, wildcards allowed (e.g. `nextcloud-app-*`). Without it, PDFs are created but not registered in Nextcloud. |
| `--telegram-config` | `telegram_config` | — | JSON file with `bot_token` and `allowed_chat_ids` for alerts |
| `--uid` | `uid` | `33` | User that owns the Nextcloud files |
| `--settle` | `settle` | `300` | Seconds without changes before converting |
| `--no-scan` | `no_scan` | `false` | Do not ask Nextcloud to register the PDFs |
| `--no-notify` | `no_notify` | `false` | No alerts |

Settings are read in this order, and the last one wins: defaults, `config.json` in the state folder, command line.

## Installation

```bash
mkdir -p /opt/pdf-watcher
cp pdf-watcher/pdf_watcher.py pdf-watcher/Dockerfile /opt/pdf-watcher/
cat > /opt/pdf-watcher/config.json <<'EOF'
{
  "data": "/srv/nextcloud/data",
  "nextcloud_container": "nextcloud"
}
EOF
python3 /opt/pdf-watcher/pdf_watcher.py      # first run: builds the image
```

Then in root's crontab:

```
*/5 * * * * python3 /opt/pdf-watcher/pdf_watcher.py
```

## State files

| File | Contents |
|---|---|
| `state.json` | For each file: signature (date and size), outcome, attempts, signature of the PDF created |
| `logs/convert.log` | Conversion log; beyond 5 MB it is rotated to `convert.log.1` |
| `tmp/` | Temporary conversion folders |
| `.lock` | Prevents two runs at the same time |
| `PAUSE` | If present, the script does nothing |

To have a file converted again, delete its entry from `state.json`, or modify the file.

# Security and privacy

- **Everything stays local.** Files are processed on the server and never sent to external services. The container does not need the Internet to work.
- **Automatic deletion.** The uploaded file is deleted as soon as the conversion ends; the result after `RETAIN_HOURS` hours, or immediately with `DELETE`. A restart deletes all jobs.
- **API keys.** With the *Key required for the API* switch on, scripts need a [key](#api-keys). The web page, however, stays open to anyone who reaches the port: anyone who opens it gets a session, so keys are for keeping track of scripts and revoking them, not for protecting the service.
- **No login for the web page.** Anyone who can reach the port can convert files and, if they know a job's identifier (128 random bits), download its result. That is why:
  - by default the service listens only on `127.0.0.1`;
  - to use it from other devices, open it only on a trusted network (home, a VPN such as Tailscale or WireGuard), or put it behind a reverse proxy with authentication (Authelia, Authentik, basic auth…);
  - **do not expose it directly to the Internet.**
- **Security headers.** Pages have a strict Content-Security-Policy, cannot be embedded in other sites (`X-Frame-Options: DENY`), and state-changing requests sent from other sites' pages are rejected (`403`).
- **Unprivileged user.** The service runs as a regular user inside the container, not as root.
- **Untrusted files.** Uploaded files are opened by complex programs (LibreOffice, FFmpeg, ImageMagick…), which may have vulnerabilities. Container isolation, the unprivileged user, and the time, size and resource limits reduce the risk. Update the image regularly (`docker compose build --pull`).
- **Archives.** Extraction uses libarchive, which rejects absolute paths and paths containing `../`.
- **Pandoc.** External resources (images embedded in documents) are looked up only in the job's folder.

# Maintenance

## Self-test

`selftest.py` generates sample files (Markdown, DOCX, EPUB, CSV, PNG, JPG, PDF, EPS, SVG, MP4, AVI, WAV, SRT, JSON, YAML, TOML, TTF, ZIP, TAR.GZ…), converts them through the API, then checks the results:

```bash
docker compose exec converter python3 /app/selftest.py                 # representative sample (~85 conversions)
docker compose exec converter python3 /app/selftest.py --all           # every target for the sample files (~330)
docker compose exec converter python3 /app/selftest.py --url http://other-server:8080
```

It exits with code 1 if at least one conversion fails, so it can be used in a monitoring script. Jobs are sent in batches of 50, so as not to exceed `MAX_QUEUE`.

## Disabling conversions

If a conversion does not work (for example a codec is missing on a certain architecture), you can remove it from the menus:

- with `DISABLED_CONVERSIONS=heic>avif,pdf>epub` in `.env`;
- or with `selftest.py --write-disabled`, which saves the failed conversions to `/work/disabled.json`.

After a restart the server recomputes the paths without those edges: if there is another route, the conversion stays available through it.

## Updating

```bash
git pull
docker compose up -d --build           # code only: a few seconds
docker compose build --pull && docker compose up -d   # programs and Debian security updates too
```

## Logs

```bash
docker compose logs -f converter
```

The server does not log individual requests (`--no-access-log`), so that file names do not end up in the logs.

# Development

## Code structure

```
server/
  converter/
    __init__.py     version
    app.py          API and web page (FastAPI); create_app() builds the application
    config.py       Settings: configuration read from environment variables
    formats.py      extensions, synonyms, categories, file name sanitising
    graph.py        Edge, Graph, is_sensible rules, default_graph() with every edge
    jobs.py         Job and JobManager: upload, queue, running the steps, cleanup
    runner.py       run(): runs programs with timeout and size limit
    tools.py        the converters, one per program
    entrypoint.sh   prepares the working folders and starts the server
    static/         web page (a single HTML file, no external dependencies)
  docs/             this documentation (the Italian file becomes /docs at build time)
  tests/            pytest tests
  selftest.py       self-test with real conversions
  Dockerfile
  pyproject.toml
nextcloud-app/      Nextcloud app (PHP + JavaScript, no build step)
pdf-watcher/        automatic PDFs for Nextcloud
docker-compose.yml
.env.example
```

## Adding a converter

1. In `server/converter/tools.py`, write a function with this signature:

   ```python
   async def my_program(job, inp: Path, out_ext: str, wd: Path) -> Path:
       out = wd / f"out.{out_ext}"
       await run(["my-program", str(inp), "-o", str(out)], timeout=600)
       return out
   ```

   `inp` is the input file, with the right extension; `wd` is an empty folder for the result; `job.progress` (from 0 to 1) and `job.step` update the progress shown to the user. To report a readable error: `raise ConvError("message")`.

2. In `default_graph()` (`server/converter/graph.py`), add the edges:

   ```python
   g.add("ext1 ext2", "dest1 dest2", tools.my_program, "My program")
   ```

   with the `cost=`, `source_only=True` or `final_only=True` options if needed.

3. If there are new extensions, add them to a category in `formats.py` (and any synonyms to `ALIASES`). If the combination might show up where it makes no sense, update `is_sensible()`.

4. If a new program is needed, add it to the `Dockerfile`.

5. Add a sample file and its targets to `selftest.py`, then run the tests and the self-test.

Multi-step paths, the web page menus and the Nextcloud menus update themselves.

## Tests

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

The tests do not need the conversion programs. They cover:

- extension recognition and name sanitising;
- reading the settings;
- path selection and combination rules;
- data conversions;
- the complete API (upload, two-step conversion, download, errors, limits, deletion, cleanup), with fake converters.

For real conversions there is `selftest.py` inside the container.

# Known issues

| Issue | Adopted solution |
|---|---|
| LibreOffice 25.2 enters an infinite loop when exporting a document with a **table** to **TXT**, and keeps writing a temporary file (more than 2.7 GB in two minutes). | DOCX/ODT → TXT goes through Pandoc; other text formats go through DOCX. On top of that, `MAX_OUTPUT_GB` stops any program that writes huge files. |
| Rarely, LibreOffice hangs at startup. | After 10 minutes the process is terminated and the conversion retried with a clean profile. |
| pdf2docx works well on "real" PDFs (with selectable text), poorly on scans. | Scans need OCR first, which the converter does not do. |
| JPEG XL is not supported by Debian 13's ImageMagick. | The format does not appear among the available ones. |
| Video → GIF: only the first 60 seconds. | Deliberate choice, to avoid GIFs of hundreds of MB. |
| Debian's `pandoc` package does not allow `--sandbox` for DOCX, ODT and EPUB. | Pandoc runs without sandbox, but with `--resource-path` limited to the job's folder. |

# FAQ

**Can I convert several files at once?**
Yes: on the web page you select several files and choose the format for each one, or for all of them together. Conversions are queued and `MAX_PARALLEL` run at a time.

**How long do files stay on the server?**
The uploaded file is deleted as soon as the conversion ends; the result after `RETAIN_HOURS` hours (6 by default), or immediately with `DELETE` or by restarting the service.

**Why is the image so big?**
Almost all of its size comes from the conversion programs: LibreOffice (~500 MB), Calibre with Qt WebEngine (~600 MB), Pandoc (~200 MB), the scientific Python libraries, the fonts. The base distribution is about 75 MB, so switching it, for example to Alpine, would make almost no difference.

**Why doesn't a format appear among the targets?**
Either no program can do that conversion in at most 3 steps, or the combination was excluded because it makes no sense (see [Sensible combinations](#sensible-combinations)), or it is disabled with `DISABLED_CONVERSIONS`.

**Does it work without the Internet?**
Yes. The Internet is only needed to build the image.
