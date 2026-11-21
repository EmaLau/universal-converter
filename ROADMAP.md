# Roadmap

Where Universal Converter is going. Released changes are in [CHANGELOG.md](CHANGELOG.md); ideas and requests are welcome as [issues](https://github.com/EmaLau/universal-converter/issues/new/choose).

**Current version:** 2.5.0 (November 2026): ~200 formats, PDF tools with OCR, API keys, ready-made Docker image, Nextcloud app, web interface in English and Italian, image for amd64 and arm64, conversion options and presets, previews, installable app, PDF slides to PowerPoint, PDF tables, web pages as articles, transcription, batch conversions.

## 2.2 — an English interface

- [x] **Nextcloud App Store**: app `universal_converter` 1.1.0 published on [apps.nextcloud.com](https://apps.nextcloud.com/apps/universal_converter) (November 2026), with a signed release archive built by `scripts/nextcloud-release.sh`.
- [x] **Screenshots** of the web page, the PDF tools and the Nextcloud menu, in the README and in the app's `info.xml` (shown on the App Store from the next app release).
- [x] **English web interface**: texts in a small dictionary (`it`, `en`) chosen from the browser language, with an IT / EN switch in the header; documentation at `/docs` in both languages.
- [x] **English error messages** from the API, chosen with `Accept-Language` (Italian stays the default for compatibility).
- [x] **ARM64 image** on ghcr.io, built natively on GitHub's ARM runners (no emulation), so Raspberry Pi and Apple Silicon users can `docker compose pull` too.

## 2.3 — PDF tools through Plico ✅

Universal Converter stays focused on **formats**; the advanced PDF tools (password, watermark and page numbers, PDF/A, organize pages, sign, redact, forms, compare…) live in the sister project [Plico](https://github.com/EmaLau/plico), which already sends Office files to the converter. The two work together instead of duplicating code.

- [x] **`PLICO_URL`**: when set, the web page shows a *More PDF tools in Plico* card (2.2.2).
- [x] Open a converted PDF directly in Plico, without downloading and uploading it again: *Open in Plico* (2.3.0).
- [x] PDF tools in the **Nextcloud menu**: covered by Plico's own Nextcloud app (*PDF tools* in the right-click menu).

## 2.4 — integrations and operations ✅ (in 2.3.0)

- [x] **Webhooks**: an optional `callback_url` in `POST /api/jobs` and `POST /api/pdf/{tool}`, called when the job ends, so clients do not need to poll; signed with `WEBHOOK_SECRET` (2.3.0).
- [x] **Download several results as one ZIP** from the web page (`POST /api/jobs/zip`, 2.2.2).
- [x] **Per-key limits**: maximum concurrent jobs and daily volume for each API key, set on the `/admin` page (2.3.0).
- [x] **Metrics** at `/metrics` (Prometheus): jobs, failures and duration per tool (2.3.0).
- [x] `/healthz` reports which conversion programs are available (2.2.2).

## 2.4.0 — a richer web page ✅

- [x] **Preview** of the result before downloading (images, first page of documents, audio and video, text).
- [x] **Conversion options** for the most used formats: image quality and size, video resolution and quality, audio bitrate, trimming, PDF pages and DPI; same-format conversions to apply them.
- [x] **Presets** ("photos for the web", "video for WhatsApp", "audio for podcasts"…), built-in and saved in the browser.
- [x] **Recent conversions** in the browser, while the files are still on the server.
- [x] **Paste** from the clipboard and convert a file **from a web address**.
- [x] **Installable app (PWA)** with the system Share menu (Web Share Target).

## 2.5.0 — slides, tables, web pages, transcription and batches ✅

- [x] **PDF → PowerPoint**: one editable slide per page (LibreOffice PDF import).
- [x] **Layout option** for PDF → Word and PDF → PowerPoint: *editable* or *identical to the original* (pages as images).
- [x] PDF → Word **recognises slides** and suggests the better alternatives in the result note.
- [x] **PDF tables** to Excel, CSV or JSON.
- [x] **Web page to PDF or Markdown** from an address: the main article, with its images.
- [x] **Audio and video transcription** to text or SRT/VTT subtitles with a local Whisper service (separate, optional).
- [x] **Batch conversion** of an archive (ZIP in, ZIP out) and whole **folders** on the web page.
- [x] Extracting the audio from a video (*Video to MP3*) and the images from a PDF (through Plico) as ready-made tools.

## Later

- Watched folder and automatic rules in Nextcloud, notifications when a long conversion ends.
- iPhone Shortcuts documented, a small CLI (`uconv file.docx pdf`), n8n / Paperless-ngx integrations.
- A "lite" image without Calibre, LibreOffice and video.

## Maintenance (ongoing)

- [x] **Monthly image rebuild** (scheduled workflow) to pick up Debian security updates, with the self-test and the malformed-file test before publishing.
- [x] **Dependabot** for the GitHub Actions used by the workflows.
- [x] **Malformed-file test** (`server/fuzz.py`): broken and "bomb" files must not bring the service down; it runs inside every image before it is published.
- [ ] Keep the NAS deployment and the repository on the same version.

## Not planned

- Accounts and logins for the web page: put it behind a reverse proxy with authentication if it must be reachable from outside a trusted network.
- A hosted (SaaS) version: the whole point is that files stay on your server.
- Conversions that need proprietary software or cloud services.
- Copies of the PDF tools that Plico already has: they are reached through Plico instead.
