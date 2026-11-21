"""Messaggi per l'utente in italiano o in inglese.

Il codice scrive i messaggi in italiano. Se la richiesta preferisce un'altra lingua (Accept-Language), errori,
passaggi e note dei lavori vengono tradotti in inglese con questa tabella. Senza Accept-Language la risposta
resta in italiano, come nelle versioni precedenti (compatibilita' con i client esistenti, es. l'app Nextcloud).
"""
from __future__ import annotations

import re

# nomi che compaiono dentro altri messaggi (titoli degli strumenti PDF, etichette delle opzioni)
TERMS = {
    "Unisci PDF": "Merge PDF", "Dividi PDF": "Split PDF", "Estrai pagine": "Extract pages",
    "Togli pagine": "Remove pages", "Ruota PDF": "Rotate PDF", "Comprimi PDF": "Compress PDF", "OCR PDF": "OCR PDF",
    "Pagine": "Pages", "Intervalli (vuoto = una pagina per file)": "Ranges (empty = one page per file)",
    "Pagine (vuoto = tutte)": "Pages (empty = all)", "Rotazione": "Rotation", "Compressione": "Compression",
    "Lingue": "Languages",
    "Qualità (1-100)": "Quality (1-100)", "Lato lungo massimo (pixel)": "Longest side (pixels)",
    "Inizio (es. 0:30)": "Start (e.g. 0:30)", "Fine (es. 1:45)": "End (e.g. 1:45)",
    "Pagine (es. 2 oppure 3-5)": "Pages (e.g. 2 or 3-5)",
}

_EN: list[tuple[str, str]] = [
    # richieste
    (r"Richiesta inviata da un altro sito", "Request sent from another site"),
    (r"Serve una chiave API nell'intestazione 'apikey'", "An API key is required in the 'apikey' header"),
    (r"Chiave API non valida", "Invalid API key"),
    (r"La chiave non ha il permesso '(.*)'", r"The key does not have the '\1' permission"),
    (r"Documentazione non generata: vedi docs/documentazione\.md", "Documentation not built: see docs/documentation.md"),
    (r"Conversione non supportata", "Conversion not supported"),
    (r"Strumento PDF sconosciuto: (.*)", r"Unknown PDF tool: \1"),
    (r"Non ancora pronto", "Not ready yet"),
    (r"Nessun risultato pronto da scaricare", "No finished result to download"),
    (r"La chiave ha gia' (\d+) lavori in corso: riprova quando finiscono", r"The key already has \1 jobs in progress: try again when they finish"),
    (r"Limite giornaliero della chiave superato", "Daily limit of the key exceeded"),
    (r"Limite non valido: (.*)", r"Invalid limit: \1"),
    (r"Metriche disattivate \(METRICS=false\)", "Metrics disabled (METRICS=false)"),
    (r"callback_url troppo lungo", "callback_url is too long"),
    (r"callback_url deve essere un indirizzo http o https", "callback_url must be an http or https address"),
    (r"callback_url: host non ammesso \((.*)\)", r"callback_url: host not allowed (\1)"),
    (r"Non so convertire \.(.*) in \.(.*)", r"Cannot convert .\1 to .\2"),
    (r"Troppi lavori in corso: riprova tra poco", "Too many jobs in progress: try again shortly"),
    (r"File vuoto: (.*)", r"Empty file: \1"),
    (r"File vuoto", "Empty file"),
    (r"File troppo grande", "File too large"),
    (r"Lavoro non trovato \(scaduto o server riavviato\)", "Job not found (expired or server restarted)"),
    (r"(.+): carica un PDF alla volta", r"\1: upload one PDF at a time"),
    (r"(.+): servono da (\d+) a (\d+) PDF", r"\1: \2 to \3 PDFs are needed"),
    (r"(.+) accetta solo PDF: (.*)", r"\1 accepts only PDFs: \2"),
    # opzioni degli strumenti PDF
    (r"intervallo di pagine non valido: '(.*)' \(esempio: 1-3, 5, 8-\)", r"invalid page range: '\1' (example: 1-3, 5, 8-)"),
    (r"intervallo di pagine non valido: '(.*)'", r"invalid page range: '\1'"),
    (r"il PDF ha (\d+) pagine: '(.*)' va oltre", r"the PDF has \1 pages: '\2' goes beyond"),
    (r"indica almeno una pagina \(esempio: 1-3, 5\)", "give at least one page (example: 1-3, 5)"),
    (r"indica le pagine \((.*)\)", r"give the pages (\1)"),
    (r"valore non valido per '(.*)': (.*)", r"invalid value for '\1': \2"),
    (r"lingue non valide: usa i codici di Tesseract, per esempio ita\+eng",
     "invalid languages: use Tesseract codes, for example ita+eng"),
    # conversioni
    (r"tempo scaduto dopo (\d+) minuti \((.*)\)", r"timed out after \1 minutes (\2)"),
    (r"(.+) ha superato la dimensione massima di un file \((.*) GB\)", r"\1 exceeded the maximum file size (\2 GB)"),
    (r"(.+) ha restituito (-?\d+): (.*)", r"\1 returned \2: \3"),
    (r"il convertitore non ha prodotto nessun file", "the converter produced no file"),
    (r"conversione (.*) -> (.*) non supportata", r"conversion \1 -> \2 not supported"),
    (r"(.+) ha prodotto un file vuoto", r"\1 produced an empty file"),
    (r"(.+): risultato vuoto", r"\1: empty result"),
    (r"il PDF ha una sola pagina: non c'e' niente da dividere", "the PDF has only one page: there is nothing to split"),
    (r"non puoi togliere tutte le pagine", "you cannot remove every page"),
    (r"LibreOffice non ha prodotto il file \(formato non riconosciuto o file danneggiato\)",
     "LibreOffice did not produce the file (unrecognised format or damaged file)"),
    (r"nessuna pagina nel PDF", "no pages in the PDF"),
    (r"ffmpeg non riuscito", "ffmpeg failed"),
    (r"formato di dati sconosciuto: (.*)", r"unknown data format: \1"),
    (r"non so scrivere (.*)", r"cannot write \1"),
    (r"file (.+) non valido: (.*)", r"invalid \1 file: \2"),
    (r"errore interno: (.*)", r"internal error: \1"),
    (r"annullato", "cancelled"),
    (r"il PDF ha (\d+) pagine: non c'è la pagina (\d+)", r"the PDF has \1 pages: there is no page \2"),
    # opzioni di conversione (options.py)
    (r"options troppo lungo", "options is too long"),
    (r"options deve essere un oggetto JSON", "options must be a JSON object"),
    (r"opzione sconosciuta: (.*)", r"unknown option: \1"),
    (r"opzione non disponibile per questa conversione: (.*)", r"option not available for this conversion: \1"),
    (r"la fine deve venire dopo l'inizio", "the end must come after the start"),
    # anteprime e indirizzi (preview.py, fetch.py)
    (r"Anteprima non disponibile per questo formato", "No preview for this format"),
    (r"Anteprima non disponibile per questo file", "No preview for this file"),
    (r"Anteprime disattivate \(PREVIEWS=false\)", "Previews disabled (PREVIEWS=false)"),
    (r"Manca il file", "The file is missing"),
    (r"File non trovato", "File not found"),
    (r"File scaricato non trovato \(scaduto o server riavviato\)", "Downloaded file not found (expired or server restarted)"),
    (r"Importazione da indirizzo disattivata \(URL_IMPORT=false\)", "Import from an address disabled (URL_IMPORT=false)"),
    (r"Indirizzo mancante", "The address is missing"),
    (r"Indirizzo troppo lungo", "The address is too long"),
    (r"Serve un indirizzo http o https", "An http or https address is needed"),
    (r"Indirizzi con nome utente e password non ammessi", "Addresses with a user name and password are not allowed"),
    (r"Indirizzo non ammesso", "Address not allowed"),
    (r"Indirizzo della rete locale non ammesso \(URL_ALLOW_PRIVATE\)", "Local network addresses are not allowed (URL_ALLOW_PRIVATE)"),
    (r"Host sconosciuto: (.*)", r"Unknown host: \1"),
    (r"Il sito ha risposto (\d+) senza indirizzo", r"The site answered \1 without an address"),
    (r"Il sito ha risposto (\d+)", r"The site answered \1"),
    (r"Certificato del sito non valido", "Invalid site certificate"),
    (r"Download non riuscito: (.*)", r"Download failed: \1"),
    (r"Troppi redirect", "Too many redirects"),
    # note sul risultato
    (r"il PDF era gia' compresso: hai ricevuto l'originale", "the PDF was already compressed: you got the original"),
    (r"dimensione ridotta del (\d+)%", r"size reduced by \1%"),
    # passaggi
    (r"(.+) \(nuovo tentativo\)", r"\1 (retry)"),
    # area admin
    (r"Area admin disattivata: imposta CONVERTER_ADMIN_PASSWORD", "Admin area disabled: set CONVERTER_ADMIN_PASSWORD"),
    (r"Accedi con la password admin", "Log in with the admin password"),
    (r"Nessuna password admin impostata", "No admin password is set"),
    (r"Richiesta non valida", "Invalid request"),
    (r"Password sbagliata", "Wrong password"),
    (r"Troppi tentativi: riprova tra qualche minuto", "Too many attempts: try again in a few minutes"),
    (r"Dai un nome alla chiave", "Give the key a name"),
    (r"Permessi sconosciuti: (.*)", r"Unknown permissions: \1"),
    (r"Chiave inesistente", "Key does not exist"),
    (r"Imposta prima una password \(CONVERTER_ADMIN_PASSWORD o file admin-password\)",
     "Set a password first (CONVERTER_ADMIN_PASSWORD or the admin-password file)"),
]
_TABLE = [(re.compile(f"^{it}$", re.S), en) for it, en in _EN]


# suffissi dei file prodotti dagli strumenti PDF (pdftools.py)
SUFFIXES = {"-unito": "-merged", "-diviso": "-split", "-estratto": "-extracted", "-senza-pagine": "-without-pages",
            "-ruotato": "-rotated", "-compresso": "-compressed"}


def filename(name: str, lang: str) -> str:
    """'relazione-compresso.pdf' -> 'relazione-compressed.pdf' in inglese."""
    if lang == "it":
        return name
    stem, dot, ext = name.rpartition(".")
    for it, en in SUFFIXES.items():
        if dot and stem.endswith(it):
            return f"{stem[:-len(it)]}{en}.{ext}"
    return name


def pick(accept_language: str | None) -> str:
    """'it' senza intestazione o se la lingua preferita e' l'italiano, altrimenti 'en'."""
    first = (accept_language or "").split(",")[0].strip().lower()
    return "it" if not first or first == "*" or first.startswith("it") else "en"


def t(msg, lang: str):
    """Traduce un messaggio (anche i nomi che contiene); se non e' nella tabella lo restituisce com'e'."""
    if lang == "it" or not isinstance(msg, str) or not msg:
        return msg
    if msg in TERMS:
        return TERMS[msg]
    for rx, en in _TABLE:
        m = rx.match(msg)
        if m:
            out = en
            for i, g in enumerate(m.groups(), 1):
                out = out.replace(f"\\{i}", TERMS.get(g, g))
            return out
    return msg
