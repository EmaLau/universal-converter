# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.4.0] - 2026-11-21

### Added
- **Conversion options**: quality, longest side and metadata removal for images; start/end trimming, maximum
  resolution, video quality, audio bitrate and mono for audio and video; DPI and pages for PDF to images.
  `GET /api/options/{src}/{dst}` lists them, `POST /api/jobs` takes them in the `options` field (JSON).
- **Same-format conversions** (`jpg` → `jpg`, `mp4` → `mp4`, `mp3` → `mp3`…) to apply the options: listed in `same`
  in `/api/formats`, so the Nextcloud menus do not change.
- **Presets** on the web page: built-in ones (photos for the web or email, video for WhatsApp, light video,
  podcast audio, first 30 seconds as MP3, PDF pages for printing) and your own, saved in the browser.
- **Preview** of the results before downloading: images, first page of PDFs and documents, audio and video players
  (30-second clips for formats browsers cannot play), text and archive listings. `GET /api/jobs/{id}/preview`,
  `preview` field in the job status, `PREVIEWS=false` to turn it off.
- **Recent conversions** on the start page, kept only in the browser, as long as the results are on the server.
- **Convert from a web address**: `POST /api/fetch` downloads the file (private and local addresses refused unless
  `URL_ALLOW_PRIVATE=true`, connection pinned to the checked IP, redirects re-checked), then `POST /api/jobs` with
  `staged`. `URL_IMPORT=false` turns it off.
- **Paste** files, images, text or addresses into the page (⌘V / Ctrl+V).
- **Installable app (PWA)** with the system **Share** menu (Web Share Target) on Android and desktop Chrome; needs HTTPS.
- Self-test: conversions with options and previews of every result.

## [2.3.0] - 2026-11-21

### Added
- **Open in Plico**: with `PLICO_URL`, every PDF result has an *Open in Plico* button. Plico fetches the file from
  the converter on its side (with its API key) and offers it straight away, without downloading and uploading it again.
- **Webhooks**: optional `callback_url` in `POST /api/jobs` and `POST /api/pdf/{tool}`. When the job ends the server
  sends the job status as JSON (`X-Converter-Event: job.done|job.error`), signed with `WEBHOOK_SECRET` if set
  (`X-Converter-Signature: sha256=...`); three attempts, no redirects, outcome in the job's `webhook` field.
  `WEBHOOK_HOSTS` limits the hosts that can be called.
- **Limits per API key**: concurrent jobs and MB per day, set on the `/admin` page (`429` when exceeded); the page
  shows today's usage and the jobs in progress of each key. The web page is never limited.
- **Prometheus metrics** at `/metrics`: finished jobs and duration per kind, queue, uploaded bytes, webhooks,
  requests refused by key limits. `METRICS=false` turns it off.

### Changed
- Error messages no longer show internal paths (`/work/jobs/<id>/...`): only the file name is left.

## [2.2.2] - 2026-11-21

### Added
- **Download all as one ZIP**: `POST /api/jobs/zip` (permission `jobs`) puts the results of several finished jobs
  in a single ZIP; the web page uses it for *Download all* instead of one download per file.
- `/healthz` lists which conversion programs are installed (`programs`).
- **Plico integration**: with `PLICO_URL` (e.g. `http://nas:30128`, or `:30128` for the same host) the web page shows
  a *More PDF tools in Plico* card. The advanced PDF tools stay in Plico instead of being copied here (see the roadmap).
- **Malformed-file test** `server/fuzz.py`: broken PDFs, image and SVG "bombs", a ZIP that expands to 1 GB, deeply
  nested JSON and random bytes must not bring the service down. It runs inside every image before it is published.
- **Monthly rebuild** of the latest release (1st of the month, no cache), published only if the self-test and the
  malformed-file test pass, so the image picks up the Debian security updates.
- Dependabot for the GitHub Actions; Nextcloud app 1.1.1 with screenshots on the App Store (no code changes).

## [2.2.1] - 2026-11-21

### Added
- **ARM64 image**: `ghcr.io/emalau/universal-converter` is now multi-platform (linux/amd64 and linux/arm64). Each
  platform is built natively on its own GitHub runner and self-tested before the two are joined in one manifest,
  so `docker compose pull` works on Raspberry Pi and Apple Silicon too.
- **Screenshots** in the README and in the Nextcloud app's `info.xml`.

### Changed
- PDF tool results are named in the language of the request (`report-compressed.pdf` instead of
  `report-compresso.pdf` with `Accept-Language: en`).

## [2.2.0] - 2026-11-21

### Added
- Nextcloud app 1.1.0, ready for the Nextcloud App Store, with the new id `universal_converter` (was `convertitore`;
  existing installations: see *Nextcloud integration* in the documentation): English texts with Italian translation (`l10n/`),
  complete `info.xml` (validated against the App Store schema), `scripts/nextcloud-release.sh` to build and sign
  the release archive.
- **English web interface**: the main page and the admin page follow the browser language, with an IT / EN switch
  in the header (remembered in the browser). Same mechanism as Plico: `static/i18n.js`.
- **English API messages** with `Accept-Language`: errors, job steps and notes; responses carry `Content-Language`.
  Without the header the messages stay in Italian, so existing clients (the Nextcloud app, scripts) see no change.
- `/docs` in English and Italian (`?lang=en|it`, otherwise from the browser language).

## [2.1.0] - 2026-11-14

### Added
- **PDF tools** on the web page and in the API (`GET /api/pdf`, `POST /api/pdf/{tool}`): merge (in the chosen
  order), split by page or range, extract pages, remove pages, rotate, compress (Ghostscript) and **OCR**
  (OCRmyPDF + Tesseract, Italian and English included) to make scans searchable.
- Ready-made Docker image on `ghcr.io/emalau/universal-converter`, published by GitHub Actions for every release
  after the self-test has passed inside it.
- GitHub Actions: tests on every push and pull request, with the real PDF programs installed.
- `CONTRIBUTING.md`, `SECURITY.md`, issue and pull request templates, this changelog.
- The self-test also checks the PDF tools.

### Changed
- `docker-compose.yml` uses the ready-made image (`docker compose pull`); `--build` still builds it locally.
- The `convert` permission of API keys also covers the PDF tools, `formats` also covers `GET /api/pdf`.

## [2.0.0] - 2026-11-13

### Added
- API keys modelled on Gokapi: `/admin` page, per-function permissions (`formats`, `convert`, `jobs`), optional
  "key required" switch, interactive API docs at `/apidocs`.
- Security headers and rejection of cross-site requests.

## [1.0.0] - 2026-11-11

First public release: about 200 formats and more than 3,000 combinations with chained conversions, web page,
JSON API, Nextcloud app "Converti in" and automatic PDFs for Nextcloud.

[Unreleased]: https://github.com/EmaLau/universal-converter/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/EmaLau/universal-converter/compare/v2.2.2...v2.3.0
[2.2.2]: https://github.com/EmaLau/universal-converter/compare/v2.2.1...v2.2.2
[2.2.1]: https://github.com/EmaLau/universal-converter/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/EmaLau/universal-converter/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/EmaLau/universal-converter/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/EmaLau/universal-converter/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/EmaLau/universal-converter/releases/tag/v1.0.0
