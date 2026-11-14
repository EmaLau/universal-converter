# Contributing

Thanks for your interest in Universal Converter! Bug reports, ideas and pull requests are all welcome.
Issues and pull requests can be written in **English or Italian**.

## Reporting a bug

Open an [issue](https://github.com/EmaLau/universal-converter/issues/new/choose) with the **Bug report** form and include:

- the version (shown by `GET /healthz`) and how you run it (ready-made image, local build, without Docker);
- what you converted (source and target format, or PDF tool and options) and the error message;
- if possible, a small file that reproduces the problem. **Do not attach private documents.**

Security problems should not be reported in a public issue: see [SECURITY.md](SECURITY.md).

## Proposing a format or a tool

Use the **Feature request** form. Say which program could do the conversion: every converter is an existing
open-source program (LibreOffice, FFmpeg, Pandoc...) called by the server, and it must be available in Debian 13.

## Development setup

```bash
git clone https://github.com/EmaLau/universal-converter.git
cd universal-converter/server
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

The tests do not need the conversion programs; the real PDF tests run only if `qpdf`, Poppler, Ghostscript and
OCRmyPDF are installed, otherwise they are skipped. For real conversions build the image and run the self-test:

```bash
docker compose up -d --build
docker compose exec converter python3 /app/selftest.py
```

- **New format**: one function in `server/converter/tools.py` and one line in `default_graph()` in `graph.py`.
  The step-by-step guide is in the [documentation](server/docs/documentation.md#adding-a-converter).
- **New PDF tool**: one function and one `PdfTool` entry in `server/converter/pdftools.py`; the web page and
  `GET /api/pdf` pick it up automatically.
- **Nextcloud app**: `nextcloud-app/` is plain PHP and JavaScript, with no build step.

## Pull requests

- Keep each pull request focused on one change, and add or update tests.
- Run `pytest` before opening it: GitHub Actions runs the same tests on every pull request.
- Update the documentation (`README.md`, `server/docs/documentation.md`) and, when you can, the Italian versions
  (`README.it.md`, `server/docs/documentazione.md`). The web interface is in Italian.
- Add a line to the *Unreleased* section of [CHANGELOG.md](CHANGELOG.md).

By contributing you agree that your contribution is licensed under the [AGPL-3.0](LICENSE).
