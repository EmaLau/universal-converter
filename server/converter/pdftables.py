"""Tabelle di un PDF in CSV, Excel (XLSX) o JSON, con il riconoscimento delle tabelle di PyMuPDF.

Funziona sui PDF con testo selezionabile (non sulle scansioni: prima serve l'OCR). Gira in un processo separato:

    python3 pdftables.py csv|xlsx|json in.pdf out.ext

- XLSX: un foglio per tabella ("p3 t1" = pagina 3, prima tabella);
- CSV: le tabelle una dopo l'altra, separate da una riga vuota;
- JSON: un elenco di tabelle con pagina e righe.
Esce con codice 3 se nel PDF non c'e' nessuna tabella.
"""
from __future__ import annotations

import csv
import json
import sys

NO_TABLES = 3
UNREADABLE = 4


def clean(cell) -> str:
    return "" if cell is None else " ".join(str(cell).split())


def extract(pdf: str) -> list[dict]:
    import pymupdf  # arriva con pdf2docx

    tables = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            for i, t in enumerate(page.find_tables().tables, 1):
                rows = [[clean(c) for c in row] for row in t.extract()]
                rows = [r for r in rows if any(r)]
                keep = [c for c in range(max((len(r) for r in rows), default=0))
                        if any(c < len(r) and r[c] for r in rows)]  # colonne sempre vuote (celle unite)
                rows = [[r[c] if c < len(r) else "" for c in keep] for r in rows]
                if len(rows) >= 2 or (rows and len(rows[0]) >= 2):
                    tables.append({"page": page.number + 1, "index": i, "rows": rows})
    return tables


def write(tables: list[dict], kind: str, out: str) -> None:
    if kind == "csv":
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel riconosce le lettere accentate
            w = csv.writer(fh)
            for n, t in enumerate(tables):
                if n:
                    w.writerow([])
                w.writerows(t["rows"])
    elif kind == "json":
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(tables, fh, ensure_ascii=False, indent=2)
    else:
        import xlsxwriter  # arriva con python-pptx

        wb = xlsxwriter.Workbook(out, {"strings_to_numbers": True, "strings_to_formulas": False,
                                       "strings_to_urls": False})
        bold = wb.add_format({"bold": True})
        for t in tables:
            ws = wb.add_worksheet(f"p{t['page']} t{t['index']}"[:31])
            for r, row in enumerate(t["rows"]):
                ws.write_row(r, 0, row, bold if r == 0 else None)
            widths = [max((len(row[c]) for row in t["rows"] if c < len(row)), default=8) for c in
                      range(max(len(row) for row in t["rows"]))]
            for c, w in enumerate(widths):
                ws.set_column(c, c, min(max(w, 8), 60) + 1)
        wb.close()


def main(argv: list[str]) -> int:
    kind, pdf, out = argv[:3]
    try:
        tables = extract(pdf)
    except Exception as e:  # noqa: BLE001 - PDF danneggiato: un messaggio, non la traccia di Python
        print(f"PDF non leggibile: {e.__class__.__name__}", file=sys.stderr)
        return UNREADABLE
    if not tables:
        print("nessuna tabella trovata nel PDF", file=sys.stderr)
        return NO_TABLES
    write(tables, kind, out)
    print(f"{len(tables)} tabelle")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
