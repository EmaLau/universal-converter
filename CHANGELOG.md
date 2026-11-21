# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/EmaLau/universal-converter/compare/v2.2.1...HEAD
[2.2.1]: https://github.com/EmaLau/universal-converter/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/EmaLau/universal-converter/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/EmaLau/universal-converter/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/EmaLau/universal-converter/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/EmaLau/universal-converter/releases/tag/v1.0.0
