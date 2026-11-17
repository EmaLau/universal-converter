# Roadmap

Where Universal Converter is going. Released changes are in [CHANGELOG.md](CHANGELOG.md); ideas and requests are welcome as [issues](https://github.com/EmaLau/universal-converter/issues/new/choose).

**Current version:** 2.1.0 (November 2026): ~200 formats, PDF tools with OCR, API keys, ready-made Docker image, Nextcloud app.

## 2.2 — an English interface

- [x] **Nextcloud App Store**: app `universal_converter` 1.1.0 published on [apps.nextcloud.com](https://apps.nextcloud.com/apps/universal_converter) (November 2026), with a signed release archive built by `scripts/nextcloud-release.sh`.
- [ ] **Screenshots** of the web page, the PDF tools and the Nextcloud menu, in the README and on the App Store.
- [ ] **English web interface**: the pages are Italian-only today. Move their texts to a small dictionary (`it`, `en`) chosen from the browser language, with a switch in the header.
- [ ] **English error messages** from the API, chosen with `Accept-Language` (Italian stays the default for compatibility).
- [ ] **ARM64 image** on ghcr.io, built natively on GitHub's ARM runners (no emulation), so Raspberry Pi and Apple Silicon users can `docker compose pull` too.

## 2.3 — more PDF tools

- [ ] **Protect and unlock**: add or remove a password (qpdf).
- [ ] **Page numbers and watermark** (text or image) on every page.
- [ ] **Images to one PDF**: several images merged into a single document, in the chosen order.
- [ ] **PDF/A** for archiving (OCRmyPDF/Ghostscript).
- [ ] **Organize pages**: reorder and rotate single pages with thumbnails in the web page.
- [ ] PDF tools in the **Nextcloud menu** too (e.g. "Merge PDFs" on several selected files, "OCR" on a scan).

## 2.4 — integrations and operations

- [ ] **Webhooks**: an optional `callback_url` in `POST /api/jobs` and `POST /api/pdf/{tool}`, called when the job ends, so clients do not need to poll.
- [ ] **Download several results as one ZIP** from the web page.
- [ ] **Per-key limits**: maximum concurrent jobs and daily volume for each API key.
- [ ] **Metrics** at `/metrics` (Prometheus): jobs, failures and duration per tool.
- [ ] `/healthz` reports which conversion programs are available.

## Maintenance (ongoing)

- [ ] **Monthly image rebuild** (scheduled workflow) to pick up Debian security updates, with the self-test before publishing.
- [ ] **Dependabot** for the GitHub Actions used by the workflows.
- [ ] Keep the NAS deployment and the repository on the same version.

## Not planned

- Accounts and logins for the web page: put it behind a reverse proxy with authentication if it must be reachable from outside a trusted network.
- A hosted (SaaS) version: the whole point is that files stay on your server.
- Conversions that need proprietary software or cloud services.
