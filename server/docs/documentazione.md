---
title: Universal Converter
pagetitle: Universal Converter — Documentazione
lang: it
---

# Panoramica

Universal Converter è un convertitore di file **self-hosted**: lo installi sul tuo computer o sul tuo server e converte documenti, fogli di calcolo, presentazioni, disegni, immagini, audio, video, sottotitoli, ebook, dati, font e archivi. È pensato come un'alternativa privata a servizi come iLovePDF o CloudConvert: i file non escono mai dalla tua rete e vengono cancellati da soli dopo qualche ora.

Il progetto ha tre parti indipendenti:

| Parte | Cartella | A cosa serve |
|---|---|---|
| **Server** | `server/` | Pagina web e API JSON. È il cuore del progetto e funziona da solo. |
| **App Nextcloud** | `nextcloud-app/` | Facoltativa: aggiunge **Converti in…** al menu dei file di Nextcloud e usa il server per convertire. |
| **PDF automatici** | `pdf-watcher/` | Facoltativo: crea un PDF accanto agli appunti Xournal++ e ai documenti Office degli utenti Nextcloud. |

## In numeri

- circa **200 estensioni** in ingresso;
- oltre **3.000 combinazioni** sorgente → destinazione;
- **15 programmi** di conversione (LibreOffice, FFmpeg, ImageMagick, Pandoc, Calibre, Poppler, Ghostscript, librsvg, LibRaw, img2pdf, pdf2docx, libarchive, 7-Zip, Xournal++, fontTools) più conversioni scritte in Python per i dati;
- un autotest che prova davvero ogni combinazione dei file di esempio (oltre 300 conversioni).

# Formati supportati

I formati sono divisi in categorie. La pagina web e l'app Nextcloud mostrano, per ogni file, solo le destinazioni che hanno senso.

| Categoria | Estensioni |
|---|---|
| Documento | PDF, DOCX, ODT, DOC, RTF, TXT, HTML, MD, TEX, RST, AsciiDoc (ADOC), Typst (TYP), Org, Pages, WordPerfect (WPD), Works (WPS), FODT, AbiWord (ABW), StarOffice (SXW), Lotus Word Pro (LWP), Hangul (HWP), Jupyter (IPYNB), Textile, DocBook (DBK), MediaWiki (WIKI), Texinfo (TEXI), OPML, txt2tags (T2T), Xournal++ (XOPP) |
| Foglio di calcolo | XLSX, ODS, XLS, CSV, TSV, Numbers, FODS, XLSB, StarOffice (SXC), DIF, SYLK (SLK), dBase (DBF), Lotus (WK1) |
| Presentazione | PPTX, ODP, PPT, Keynote (KEY), FODP, StarOffice (SXI) |
| Disegno | SVG, EPS, PS, Visio (VSD, VSDX), ODG, Publisher (PUB), CorelDRAW (CDR), WMF, EMF |
| Immagine | JPG, PNG, WEBP, HEIC, AVIF, GIF, TIFF, BMP, ICO, JPEG 2000 (JP2), QOI, TGA, PSD, PPM, PBM, PGM, PNM, PCX, DDS, HDR, GIMP (XCF), XPM, APNG e i RAW delle fotocamere (DNG, CR2, CR3, NEF, ARW, RAF, ORF, RW2) |
| Audio | MP3, M4A, WAV, FLAC, OGG, OPUS, AAC, AIFF, WMA, AC3, MKA, AMR, DTS, APE, WavPack (WV), CAF, AU, MP2, TTA |
| Video | MP4, MKV, MOV, WEBM, AVI, WMV, FLV, M4V, 3GP, MTS, MPG, TS, OGV, VOB, MXF, ASF, RM, RMVB, F4V, DIVX, DV |
| Sottotitoli | SRT, VTT, ASS, SSA |
| Ebook | EPUB, MOBI, AZW3, AZW, FB2, LIT, PDB, HTMLZ, TXTZ, LRF, fumetti (CBZ, CBR, CB7), CHM, SNB, TCR, PML |
| Dati | JSON, YAML, TOML |
| Font | TTF, OTF, WOFF, WOFF2 |
| Archivio | ZIP, 7Z, TAR.GZ, TAR.XZ, TAR.BZ2, TAR.ZST, TAR, RAR, ISO, CAB, CPIO, LHA |

Sono riconosciuti anche i sinonimi più comuni: `.jpeg` e `.jfif` come JPG, `.tif` come TIFF, `.yml` come YAML, `.tgz` come TAR.GZ, `.docm` come DOCX e così via.

L'elenco completo e sempre aggiornato delle combinazioni si trova nella pagina web, alla voce **Tutti i formati supportati**, oppure nell'API `GET /api/formats`.

## Alcuni esempi

| Da | A | Come |
|---|---|---|
| Word, ODT, RTF, Pages | PDF | LibreOffice |
| PDF | Word | pdf2docx (solo da un PDF originale, non da uno appena generato) |
| PDF | JPG o PNG | Poppler, un'immagine per pagina; con più pagine si riceve uno ZIP |
| PDF | SVG | Poppler, un SVG vettoriale per pagina |
| HEIC (foto iPhone) | JPG | ImageMagick |
| Video | MP4 | FFmpeg: se i codec sono già compatibili copia i flussi senza ricodificare, quindi in pochi secondi |
| Video | GIF | FFmpeg, i primi 60 secondi, 12 fotogrammi al secondo, al massimo 640 px di larghezza |
| Markdown | PowerPoint | Pandoc: una slide per ogni titolo |
| Markdown | PDF | Pandoc (MD → DOCX) + LibreOffice (DOCX → PDF) |
| JSON | Excel | Python (JSON → CSV) + LibreOffice (CSV → XLSX) |
| Excel | JSON | LibreOffice (XLSX → CSV) + Python (CSV → JSON) |
| SRT | VTT | FFmpeg |
| TTF, OTF | WOFF2 | fontTools |
| RAR, 7Z, ISO | ZIP | libarchive |

# Installazione

## Con Docker Compose (consigliato)

Serve Docker con il plugin Compose.

```bash
git clone <indirizzo del repository> universal-converter
cd universal-converter
cp .env.example .env        # facoltativo
docker compose up -d --build
```

Poi apri <http://localhost:8080>.

La prima build scarica LibreOffice, FFmpeg, Calibre e gli altri programmi: circa 500 MB da scaricare e un'immagine finale di circa 3,5 GB. A seconda della connessione richiede 5-20 minuti. Le build successive sono molto più veloci: i programmi stanno in un livello separato dell'immagine e restano in cache, e se cambi solo il codice la build richiede pochi secondi.

Per controllare che tutto funzioni:

```bash
docker compose exec converter python3 /app/selftest.py
```

## Con Docker, senza Compose

```bash
docker build -t universal-converter server/
docker run -d --name universal-converter -p 127.0.0.1:8080:8080 \
  -v converter-work:/work universal-converter
```

## Senza Docker (sviluppo)

Il server è un normale pacchetto Python (FastAPI). Per lavorare sul codice:

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
WORK_DIR=/tmp/converter .venv/bin/uvicorn --factory converter.app:create_app --reload
```

Senza i programmi di conversione installati sul computer, la pagina e l'API funzionano, ma le conversioni falliscono. Per le conversioni vere usa Docker.

## Architetture

L'immagine si basa su Debian 13 (trixie) e funziona sia su x86-64 (PC, NAS, server) sia su ARM64 (Mac con Apple Silicon, Raspberry Pi 4/5).

# Configurazione

Le impostazioni si scrivono in `.env`, nella cartella principale del progetto (parti da `.env.example`). Docker Compose le passa al container come variabili d'ambiente.

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `CONVERTER_BIND` | `127.0.0.1` | Indirizzo su cui pubblicare il servizio. `127.0.0.1` lo rende raggiungibile solo dal computer stesso, `0.0.0.0` da tutta la rete. |
| `CONVERTER_PORT` | `8080` | Porta pubblicata. |
| `MAX_PARALLEL` | `2` | Conversioni eseguite contemporaneamente; le altre aspettano in coda. Ogni LibreOffice o FFmpeg usa molta CPU e memoria: alzalo solo se il server ha risorse. |
| `MAX_QUEUE` | `200` | Lavori tenuti in memoria (in coda + in corso + finiti e non ancora cancellati). Oltre questo numero il server risponde `503 Troppi lavori in corso`. |
| `RETAIN_HOURS` | `6` | Ore dopo le quali il risultato di un lavoro finito viene cancellato. |
| `MAX_UPLOAD_GB` | `20` | Dimensione massima di un file caricato. |
| `MAX_OUTPUT_GB` | `50` | Dimensione massima di **ogni file** scritto da un programma durante una conversione. Se un programma si blocca e continua a scrivere, il sistema lo ferma al raggiungimento del limite e il lavoro finisce con un errore chiaro, prima che il disco si riempia. |
| `DISABLED_CONVERSIONS` | vuoto | Conversioni da nascondere, separate da virgole. Esempio: `heic>avif,pdf>epub`. |
| `CONVERTER_CPUS` | `4` | CPU massime del container. |
| `CONVERTER_MEMORY` | `4G` | Memoria massima del container. |
| `CONVERTER_UID`, `CONVERTER_GID` | `1000` | Utente e gruppo che eseguono il servizio dentro il container. Sono anche i proprietari dei file di lavoro: impostali se monti una cartella del server al posto del volume. |
| `TZ` | `Europe/Rome` | Fuso orario. |

Dopo aver cambiato `.env`: `docker compose up -d`.

## Cartella di lavoro

Tutti i file temporanei stanno in `/work` dentro il container (in Docker Compose è il volume `converter-work`):

| Percorso | Contenuto |
|---|---|
| `/work/jobs/<id>/` | Un lavoro: file caricato, passaggi intermedi, risultato. |
| `/work/tmp/` | File temporanei dei programmi. |
| `/work/home/` | Profili e cache dei programmi (Calibre, Xournal++…). |
| `/work/disabled.json` | Conversioni disattivate (facoltativo, vedi [Manutenzione](#manutenzione)). |

All'avvio la cartella `jobs` viene svuotata: i lavori vivono solo in memoria, quindi quelli di un avvio precedente non sono più raggiungibili.

# Uso della pagina web

La pagina principale mostra una griglia di **strumenti** pronti ("Word in PDF", "HEIC in JPG", "JSON in Excel"…), filtrabili per categoria, più lo strumento **Qualsiasi formato**.

1. Scegli uno strumento, oppure **Qualsiasi formato**.
2. Seleziona uno o più file, oppure trascinali nella pagina.
3. Per ogni file scegli il formato di arrivo. Con più file, il menu in basso **Converti tutti in** imposta lo stesso formato per tutti.
4. Premi **Converti**. Ogni file mostra caricamento, posizione in coda, passaggio in corso e, per audio, video ed ebook, la percentuale.
5. Quando un file è pronto compare **Scarica**; con più file pronti anche **Scarica tutti**.

Sotto la griglia, **Tutti i formati supportati** elenca per ogni formato di partenza tutte le destinazioni possibili.

Note:

- I file più grandi del limite (`MAX_UPLOAD_GB`) vengono segnalati subito, senza caricarli.
- Se una conversione fallisce, il messaggio spiega il motivo e il tasto **Riprova** la rimette in coda.
- I risultati restano scaricabili per `RETAIN_HOURS` ore, poi vengono cancellati.
- La pagina segue il tema chiaro o scuro del sistema operativo.

# API

L'API usa JSON ed è la stessa usata dalla pagina web e dall'app Nextcloud. Non richiede autenticazione: vedi [Sicurezza](#sicurezza-e-privacy).

## Riepilogo

| Metodo | Percorso | Descrizione |
|---|---|---|
| `GET` | `/healthz` | Stato del servizio |
| `GET` | `/api/formats` | Formati e combinazioni supportate |
| `GET` | `/api/plan/{src}/{dst}` | Passaggi previsti per una conversione |
| `POST` | `/api/jobs` | Crea un lavoro caricando un file |
| `GET` | `/api/jobs/{id}` | Stato di un lavoro |
| `GET` | `/api/jobs/{id}/download` | Scarica il risultato |
| `DELETE` | `/api/jobs/{id}` | Cancella subito un lavoro e i suoi file |
| `GET` | `/docs` | Questa documentazione |

## `GET /healthz`

```json
{"ok": true, "version": "2.0.0", "jobs": 3, "running": 1, "queued": 0}
```

Usato anche dall'healthcheck di Docker.

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

`inputs` contiene anche i sinonimi (`jpeg`, `yml`…), con le stesse destinazioni del formato principale.

## `GET /api/plan/{src}/{dst}`

```bash
curl http://localhost:8080/api/plan/json/xlsx
```

```json
[{"tool": "Python", "from": "json", "to": "csv"},
 {"tool": "LibreOffice", "from": "csv", "to": "xlsx"}]
```

Risponde `404` se la conversione non è supportata.

## `POST /api/jobs`

Richiesta `multipart/form-data` con i campi:

| Campo | Obbligatorio | Descrizione |
|---|---|---|
| `file` | sì | Il file da convertire. Il formato di partenza si ricava dall'estensione del nome. |
| `target` | sì | Estensione di arrivo, per esempio `pdf`. |
| `meta` | no | Testo libero (al massimo 2.000 caratteri) restituito nello stato del lavoro: utile per chi integra il servizio. |

Risposta `201` con lo stato del lavoro (vedi sotto). Errori:

| Codice | Quando |
|---|---|
| `400` | Conversione non supportata, oppure file vuoto |
| `413` | File più grande di `MAX_UPLOAD_GB` |
| `503` | Troppi lavori in memoria (`MAX_QUEUE`): riprova tra poco |

Gli errori hanno sempre la forma `{"detail": "messaggio"}`.

## `GET /api/jobs/{id}`

```json
{
  "id": "4f6c0e1d2b9a4c8e9f0a1b2c3d4e5f60",
  "filename": "relazione.docx",
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

| Campo | Significato |
|---|---|
| `state` | `queued` (in coda), `running` (in corso), `done` (finito), `error` (fallito) |
| `position` | Solo con `queued`: posizione nella coda, a partire da 1 |
| `progress` | Da 0 a 1 quando il programma comunica l'avanzamento (FFmpeg, Calibre, PDF → SVG), altrimenti `null` |
| `step` | Passaggio in corso, con il numero del passaggio se sono più di uno |
| `error` | Con `error`: il motivo, mostrabile all'utente |
| `out_name`, `size` | Con `done`: nome del file risultante e dimensione in byte |

Risponde `404` se il lavoro non esiste: mai creato, già cancellato, scaduto o server riavviato.

## `GET /api/jobs/{id}/download`

Restituisce il file con il nome giusto (`Content-Disposition`), anche con caratteri accentati. Risponde `409` se il lavoro non è ancora finito.

Il nome del risultato è quello del file originale con la nuova estensione: `Relazione finale.docx` → `Relazione finale.pdf`. Se il risultato contiene più file, per esempio le pagine di un PDF convertite in immagini, si riceve uno ZIP.

## `DELETE /api/jobs/{id}`

Cancella subito il lavoro e i suoi file. Se è ancora in corso, lo interrompe. Risponde `{"ok": true}`.

## Esempio completo con curl

```bash
id=$(curl -s -F file=@relazione.docx -F target=pdf http://localhost:8080/api/jobs | jq -r .id)

while [ "$(curl -s http://localhost:8080/api/jobs/$id | jq -r .state)" != "done" ]; do sleep 1; done

curl -OJ http://localhost:8080/api/jobs/$id/download
curl -X DELETE http://localhost:8080/api/jobs/$id
```

## Esempio in Python

```python
import time
import requests

API = "http://localhost:8080"

with open("foto.heic", "rb") as fh:
    job = requests.post(f"{API}/api/jobs", files={"file": fh}, data={"target": "jpg"}).json()

while (st := requests.get(f"{API}/api/jobs/{job['id']}").json())["state"] in ("queued", "running"):
    time.sleep(1)

if st["state"] == "error":
    raise SystemExit(st["error"])

with open(st["out_name"], "wb") as out:
    out.write(requests.get(f"{API}/api/jobs/{job['id']}/download").content)
requests.delete(f"{API}/api/jobs/{job['id']}")
```

# Come funziona

## Il grafo delle conversioni

Ogni programma di conversione è descritto da **archi** "estensione → estensione". Per esempio LibreOffice ha un arco DOCX → PDF, Pandoc un arco MD → DOCX, Python un arco JSON → CSV.

All'avvio, per ogni formato di partenza il server calcola con l'algoritmo di **Dijkstra** il percorso più economico verso tutti gli altri formati, con al massimo **3 passaggi**. Così, senza scrivere a mano ogni combinazione:

- Markdown → PDF diventa Pandoc (MD → DOCX) + LibreOffice (DOCX → PDF);
- CorelDRAW → PNG diventa LibreOffice (CDR → PDF) + Poppler (PDF → PNG);
- YAML → Excel diventa Python (YAML → CSV) + LibreOffice (CSV → XLSX).

Ogni arco ha un **costo**, 1 di base. Alcuni costano di più per far preferire alternative migliori quando esistono: Calibre (1,2) e Pandoc da DOCX/ODT/EPUB (1,5).

Due proprietà speciali:

- **solo dal file originale** (`source_only`): l'arco si usa solo come primo passaggio. PDF → Word con pdf2docx funziona bene su un PDF vero, ma non avrebbe senso dopo un DOCX → PDF. Lo stesso vale per Markdown → PowerPoint e per WOFF → TTF/OTF.
- **finale** (`final_only`): l'arco produce più file (le pagine di un PDF come immagini o SVG), quindi dopo non si può aggiungere altro.

## Le combinazioni sensate

Tecnicamente si potrebbe trasformare un foglio Excel in MP3 (Excel → PDF → immagine → video…), ma non serve a nessuno. Una serie di regole toglie queste combinazioni dai menu:

- audio solo verso audio; video solo verso video, audio e GIF;
- sottotitoli e font solo verso la stessa categoria;
- dati (JSON, YAML, TOML) solo verso dati e fogli di calcolo, e viceversa;
- archivi solo verso archivi;
- immagini verso immagini o PDF (più GIF/APNG → video);
- fogli di calcolo verso documenti solo in PDF, HTML, TXT o Markdown;
- presentazioni verso documenti solo in PDF;
- disegni verso immagini, disegni o PDF;
- le presentazioni si possono creare da un documento solo se è in un linguaggio di markup (Markdown, reStructuredText, Org, HTML, Textile).

## I lavori

1. **Caricamento.** Il file viene scritto in `/work/jobs/<id>/` a blocchi di 4 MB, controllando la dimensione massima. Il nome viene ripulito da percorsi e caratteri non stampabili.
2. **Coda.** Il lavoro aspetta finché non c'è un posto libero tra i `MAX_PARALLEL`.
3. **Passaggi.** Ogni passaggio lavora in una propria cartella (`step1`, `step2`…). Il risultato di un passaggio diventa l'ingresso del successivo, con l'estensione corretta. Un file vuoto viene considerato un errore.
4. **Fine.** Il file caricato viene cancellato subito; il risultato resta disponibile per `RETAIN_HOURS` ore.
5. **Pulizia.** Ogni 10 minuti il server cancella i lavori finiti da più di `RETAIN_HOURS` ore.

## Esecuzione dei programmi

- I programmi vengono avviati **senza shell**, con gli argomenti separati: un nome di file non può diventare un comando.
- Ogni programma ha un **tempo massimo**: 10 minuti per LibreOffice, 30 per pdf2docx e Calibre, 4 ore per FFmpeg. Allo scadere viene terminato insieme a tutti i suoi processi figli.
- Ogni file scritto da un programma è limitato a `MAX_OUTPUT_GB`.
- In caso di errore, l'utente vede le ultime righe di output del programma.
- LibreOffice usa un profilo separato per ogni lavoro, così più conversioni possono girare in parallelo. Se all'avvio resta bloccato, cosa che capita di rado, viene ritentato una volta con un profilo pulito.

## Scelte per qualità e velocità

- **Video**: verso MP4, MOV, M4V, TS e FLV, se i codec sono già H.264 (o HEVC dove il contenitore lo permette) con audio AAC o MP3, i flussi vengono **copiati senza ricodifica**. Verso MKV si prova sempre prima la copia. Solo se non è possibile si ricodifica: H.264 CRF 21 con AAC, VP9 per WEBM, Theora per OGV, WMV2, MPEG-2.
- **Immagini**: qualità 90 per JPG, WEBP, HEIC e AVIF. Rotazione automatica secondo i dati EXIF. Sfondo bianco al posto della trasparenza verso JPG e BMP. Le icone ICO contengono tutte le dimensioni da 16 a 256 px.
- **CSV**: il separatore (virgola, punto e virgola o tabulazione) viene riconosciuto da solo.
- **Testo da DOCX/ODT**: si usa Pandoc invece di LibreOffice, per un problema noto (vedi [Problemi noti](#problemi-noti)).
- **Dati → CSV**: un oggetto con una sola lista (`{"persone": [...]}`) diventa una tabella con una riga per elemento. Le colonne sono l'unione delle chiavi; i valori annidati diventano testo JSON nella cella.
- **Font**: da WOFF/WOFF2 si torna al formato giusto in base ai contorni del font, TrueType → TTF e PostScript/CFF → OTF. Se si sceglie quello sbagliato, l'errore lo spiega.

# Integrazione con Nextcloud

L'app `nextcloud-app/` (id `convertitore`, Nextcloud 30-36) aggiunge al menu di ogni file il sottomenu **Converti in…**, con i formati possibili per quel file. Funziona anche su più file selezionati insieme: in quel caso mostra solo i formati comuni a tutti.

## Installazione

1. Copia la cartella `nextcloud-app` in `custom_apps/convertitore` dell'installazione di Nextcloud, con proprietario l'utente del web server (di solito `www-data`, UID 33):

   ```bash
   cp -r nextcloud-app /var/www/html/custom_apps/convertitore
   chown -R www-data:www-data /var/www/html/custom_apps/convertitore
   ```

2. Attivala e indica l'indirizzo del convertitore. Deve essere raggiungibile **dal server Nextcloud**, non dal browser:

   ```bash
   occ app:enable convertitore
   occ config:app:set convertitore converter_url --value=http://192.0.2.10:8080
   ```

   Con Docker, `occ` si lancia così: `docker exec -u 33 <container-nextcloud> php occ ...`.

Finché `converter_url` non è impostato, l'app non mostra nessuna voce. Gli indirizzi privati (192.168.x.x, 10.x.x.x…) sono ammessi: l'app li autorizza esplicitamente nel client HTTP di Nextcloud.

## Come funziona

1. L'utente sceglie **Converti in ▸ PDF**. Il browser chiama l'app, che invia il file al convertitore.
2. Il browser chiede lo stato ogni 1,5-5 secondi e mostra un avviso con coda, passaggio e percentuale.
3. Quando il convertitore ha finito, il risultato viene salvato **accanto all'originale**, con un nome libero: `relazione.pdf`, poi `relazione (2).pdf`… Se la cartella è in sola lettura (per esempio una condivisione), il file va nella cartella principale dell'utente e l'avviso lo dice.
4. Il nuovo file compare subito nella cartella aperta.

Il salvataggio lo fa chi arriva prima: il browser oppure un **lavoro in background di Nextcloud**. Così il file arriva anche se l'utente chiude la pagina. Serve il cron di Nextcloud attivo (Impostazioni → Amministrazione → Impostazioni di base → Cron).

L'elenco dei formati viene chiesto al convertitore e tenuto in cache per un'ora; se il convertitore non risponde, l'app riprova dopo un minuto. Dopo aver aggiunto formati al server, per vederli subito svuota la cache o aspetta un'ora.

## Problemi frequenti

| Sintomo | Causa probabile |
|---|---|
| Nessuna voce "Converti in" | `converter_url` non impostato, oppure il convertitore non è raggiungibile da Nextcloud. Controlla il log di Nextcloud: compare `Convertitore non raggiungibile`. |
| La voce manca solo per alcuni file | Il formato non è supportato, oppure il file non è leggibile dall'utente. |
| "Conversione sconosciuta o scaduta" | Sono passate più di 48 ore, oppure la cache di Nextcloud è stata svuotata. |
| "Il convertitore ha perso il lavoro" | Il convertitore è stato riavviato durante la conversione: riprova. |

# PDF automatici per Nextcloud

`pdf-watcher/pdf_watcher.py` crea automaticamente un PDF accanto a ogni file `.xopp` (Xournal++), `.doc`, `.docx`, `.odt`, `.rtf`, `.ppt`, `.pptx` e `.odp` degli utenti Nextcloud, con il nome `file.estensione.pdf` (per esempio `Appunti.xopp` → `Appunti.xopp.pdf`). È utile per leggere gli appunti dal telefono o condividerli con chi non ha i programmi giusti.

È indipendente dal server: gira da cron, come root, sulla macchina che ospita i dati di Nextcloud, e usa Docker.

## Funzionamento

A ogni esecuzione lo script:

1. controlla che esista l'immagine Docker di conversione e, se manca, la costruisce dal `Dockerfile` della sua cartella;
2. scorre i file degli utenti in `<data>/<utente>/files`, saltando file e cartelle nascosti;
3. per ogni file nuovo o modificato, **fermo da almeno 5 minuti** (così non crea un PDF a ogni salvataggio), lo converte;
4. controlla il risultato: deve avere almeno una pagina, e per Xournal++ lo stesso numero di pagine dell'originale;
5. copia il PDF accanto all'originale con il proprietario giusto, passando da un file temporaneo `.part` che Nextcloud ignora;
6. chiede a Nextcloud di registrare il nuovo file (`occ files:scan`);
7. dopo 3 tentativi falliti sullo stesso file manda un avviso, se Telegram è configurato.

Garanzie:

- **non cancella mai nulla**;
- **non sovrascrive un PDF che non ha creato lui**: se trova un PDF con quel nome fatto da altri, o modificato dopo, lo lascia stare;
- se il file originale cambia durante la conversione, rinuncia e riprova la volta dopo;
- ogni conversione avviene in un container **senza rete**, in sola lettura, senza privilegi, con limiti di memoria (4 GB), CPU (4), processi (512) e tempo (10 minuti); vede solo la cartella dell'utente, e anche quella in sola lettura;
- una sola esecuzione alla volta (file `.lock`); un file `PAUSE` nella cartella di stato sospende tutto.

## Opzioni

| Opzione | Chiave in `config.json` | Predefinito | Descrizione |
|---|---|---|---|
| `--data` | `data` | — (obbligatoria) | Cartella `data` di Nextcloud |
| `--base` | — | cartella dello script | Dove tenere stato, log, lock e `config.json` |
| `--image` | `image` | `pdf-watcher:1` | Nome dell'immagine Docker |
| `--nextcloud-container` | `nextcloud_container` | — | Nome del container di Nextcloud, anche con `*` (es. `nextcloud-app-*`). Senza, i PDF vengono creati ma non registrati in Nextcloud. |
| `--telegram-config` | `telegram_config` | — | File JSON con `bot_token` e `allowed_chat_ids` per gli avvisi |
| `--uid` | `uid` | `33` | Utente proprietario dei file di Nextcloud |
| `--settle` | `settle` | `300` | Secondi senza modifiche prima di convertire |
| `--no-scan` | `no_scan` | `false` | Non chiedere a Nextcloud di registrare i PDF |
| `--no-notify` | `no_notify` | `false` | Niente avvisi |

Le impostazioni si leggono in quest'ordine, e l'ultima vince: valori predefiniti, `config.json` nella cartella di stato, riga di comando.

## Installazione

```bash
mkdir -p /opt/pdf-watcher
cp pdf-watcher/pdf_watcher.py pdf-watcher/Dockerfile /opt/pdf-watcher/
cat > /opt/pdf-watcher/config.json <<'EOF'
{
  "data": "/srv/nextcloud/data",
  "nextcloud_container": "nextcloud"
}
EOF
python3 /opt/pdf-watcher/pdf_watcher.py      # prima esecuzione: costruisce l'immagine
```

Poi in cron di root:

```
*/5 * * * * python3 /opt/pdf-watcher/pdf_watcher.py
```

## File di stato

| File | Contenuto |
|---|---|
| `state.json` | Per ogni file: firma (data e dimensione), esito, tentativi, firma del PDF creato |
| `logs/convert.log` | Registro delle conversioni; superati i 5 MB viene ruotato in `convert.log.1` |
| `tmp/` | Cartelle temporanee delle conversioni |
| `.lock` | Impedisce due esecuzioni contemporanee |
| `PAUSE` | Se esiste, lo script non fa nulla |

Per far riconvertire un file basta cancellare la sua voce da `state.json`, oppure modificare il file.

# Sicurezza e privacy

- **Tutto in locale.** I file vengono elaborati sul server e non vengono mai inviati a servizi esterni. Il container non ha bisogno di Internet per funzionare.
- **Cancellazione automatica.** Il file caricato viene cancellato appena finisce la conversione; il risultato dopo `RETAIN_HOURS` ore, oppure subito con `DELETE`. Un riavvio cancella tutti i lavori.
- **Nessun login.** Chiunque raggiunga la porta può convertire file e, se conosce l'identificativo di un lavoro (128 bit casuali), scaricarne il risultato. Per questo:
  - di base il servizio risponde solo su `127.0.0.1`;
  - per usarlo da altri dispositivi, aprilo solo in una rete fidata (casa, VPN come Tailscale o WireGuard), oppure mettilo dietro un reverse proxy con autenticazione (Authelia, Authentik, basic auth…);
  - **non esporlo direttamente su Internet.**
- **Utente non privilegiato.** Il servizio gira come utente normale dentro il container, non come root.
- **File non fidati.** I file caricati vengono aperti da programmi complessi (LibreOffice, FFmpeg, ImageMagick…), che possono avere vulnerabilità. L'isolamento del container, l'utente non privilegiato, i limiti di tempo, di dimensione e di risorse riducono i rischi. Aggiorna regolarmente l'immagine (`docker compose build --pull`).
- **Archivi.** L'estrazione usa libarchive, che rifiuta i percorsi assoluti e quelli con `../`.
- **Pandoc.** Le risorse esterne (immagini incluse nei documenti) vengono cercate solo nella cartella del lavoro.

# Manutenzione

## Autotest

`selftest.py` genera file di prova (Markdown, DOCX, EPUB, CSV, PNG, JPG, PDF, EPS, SVG, MP4, AVI, WAV, SRT, JSON, YAML, TOML, TTF, ZIP, TAR.GZ…) e li converte tramite l'API, poi controlla il risultato:

```bash
docker compose exec converter python3 /app/selftest.py                 # campione rappresentativo (~85 conversioni)
docker compose exec converter python3 /app/selftest.py --all           # tutte le destinazioni dei file di prova (~330)
docker compose exec converter python3 /app/selftest.py --url http://altro-server:8080
```

Esce con codice 1 se almeno una conversione fallisce, quindi si può usare in uno script di controllo. I lavori vengono inviati a gruppi di 50, per non superare `MAX_QUEUE`.

## Disattivare conversioni

Se una conversione non funziona (per esempio manca un codec in una certa architettura), puoi toglierla dai menu:

- con `DISABLED_CONVERSIONS=heic>avif,pdf>epub` in `.env`;
- oppure con `selftest.py --write-disabled`, che salva le conversioni fallite in `/work/disabled.json`.

Dopo il riavvio il server ricalcola i percorsi senza quegli archi: se esiste un'altra strada, la conversione resta disponibile passando da lì.

## Aggiornare

```bash
git pull
docker compose up -d --build           # solo il codice: pochi secondi
docker compose build --pull && docker compose up -d   # anche i programmi e gli aggiornamenti di sicurezza di Debian
```

## Log

```bash
docker compose logs -f converter
```

Il server non registra le singole richieste (`--no-access-log`), per non lasciare nei log i nomi dei file.

# Sviluppo

## Struttura del codice

```
server/
  converter/
    __init__.py     versione
    app.py          API e pagina web (FastAPI); create_app() crea l'applicazione
    config.py       Settings: impostazioni lette dalle variabili d'ambiente
    formats.py      estensioni, sinonimi, categorie, pulizia dei nomi dei file
    graph.py        Edge, Graph, regole is_sensible, default_graph() con tutti gli archi
    jobs.py         Job e JobManager: caricamento, coda, esecuzione dei passaggi, pulizia
    runner.py       run(): esecuzione dei programmi con tempo e dimensione massimi
    tools.py        i convertitori, uno per programma
    entrypoint.sh   prepara le cartelle di lavoro e avvia il server
    static/         pagina web (un solo file HTML, senza dipendenze esterne)
  docs/             questa documentazione (diventa /docs durante la build)
  tests/            test con pytest
  selftest.py       autotest delle conversioni vere
  Dockerfile
  pyproject.toml
nextcloud-app/      app Nextcloud (PHP + JavaScript, senza build)
pdf-watcher/        PDF automatici per Nextcloud
docker-compose.yml
.env.example
```

## Aggiungere un convertitore

1. In `server/converter/tools.py` scrivi una funzione con questa firma:

   ```python
   async def mio_programma(job, inp: Path, out_ext: str, wd: Path) -> Path:
       out = wd / f"out.{out_ext}"
       await run(["mio-programma", str(inp), "-o", str(out)], timeout=600)
       return out
   ```

   `inp` è il file di ingresso, con l'estensione giusta; `wd` è una cartella vuota per il risultato; `job.progress` (da 0 a 1) e `job.step` aggiornano l'avanzamento mostrato all'utente. Per segnalare un errore leggibile: `raise ConvError("messaggio")`.

2. In `default_graph()` (`server/converter/graph.py`) aggiungi gli archi:

   ```python
   g.add("ext1 ext2", "dest1 dest2", tools.mio_programma, "Mio programma")
   ```

   con le opzioni `cost=`, `source_only=True` o `final_only=True` se servono.

3. Se ci sono nuove estensioni, aggiungile a una categoria in `formats.py` (ed eventualmente i sinonimi in `ALIASES`). Se la combinazione rischia di comparire dove non ha senso, aggiorna `is_sensible()`.

4. Se serve un programma nuovo, aggiungilo al `Dockerfile`.

5. Aggiungi un file di prova e le destinazioni in `selftest.py`, poi lancia test e autotest.

I percorsi in più passaggi, i menu della pagina web e quelli di Nextcloud si aggiornano da soli.

## Test

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

I test non richiedono i programmi di conversione. Coprono:

- riconoscimento delle estensioni e pulizia dei nomi;
- lettura delle impostazioni;
- scelta dei percorsi e regole sulle combinazioni;
- conversioni di dati;
- l'API completa (caricamento, conversione in due passaggi, download, errori, limiti, cancellazione, pulizia), con convertitori finti.

Per le conversioni vere c'è `selftest.py` dentro il container.

# Problemi noti

| Problema | Soluzione adottata |
|---|---|
| LibreOffice 25.2 entra in un ciclo infinito quando esporta in **TXT** un documento con una **tabella**, e continua a scrivere un file temporaneo (oltre 2,7 GB in due minuti). | DOCX/ODT → TXT passa da Pandoc; gli altri formati di testo passano da DOCX. In più, `MAX_OUTPUT_GB` ferma qualsiasi programma che scriva file enormi. |
| Raramente LibreOffice resta bloccato all'avvio. | Dopo 10 minuti il processo viene terminato e la conversione ritentata con un profilo pulito. |
| pdf2docx funziona bene sui PDF "veri" (con testo selezionabile), male sulle scansioni. | Per le scansioni serve prima un OCR, che il convertitore non fa. |
| JPEG XL non è supportato dall'ImageMagick di Debian 13. | Il formato non compare tra quelli disponibili. |
| Video → GIF: solo i primi 60 secondi. | Scelta voluta, per evitare GIF di centinaia di MB. |
| Il pacchetto `pandoc` di Debian non permette `--sandbox` per DOCX, ODT ed EPUB. | Pandoc gira senza sandbox, ma con `--resource-path` limitato alla cartella del lavoro. |

# Domande frequenti

**Posso convertire più file insieme?**
Sì: nella pagina web selezioni più file e scegli il formato per ciascuno, o per tutti insieme. Le conversioni vanno in coda e ne girano `MAX_PARALLEL` alla volta.

**Quanto tempo restano i file sul server?**
Il file caricato viene cancellato appena finisce la conversione; il risultato dopo `RETAIN_HOURS` ore (6 di base), oppure subito con `DELETE` o riavviando il servizio.

**Perché l'immagine è così grande?**
Il peso viene quasi tutto dai programmi di conversione: LibreOffice (~500 MB), Calibre con Qt WebEngine (~600 MB), Pandoc (~200 MB), le librerie Python scientifiche, i font. La distribuzione di base pesa circa 75 MB, quindi cambiarla, per esempio con Alpine, non farebbe quasi nessuna differenza.

**Perché un formato non compare tra le destinazioni?**
O nessun programma sa fare quella conversione in al massimo 3 passaggi, o la combinazione è stata esclusa perché non ha senso (vedi [Le combinazioni sensate](#le-combinazioni-sensate)), oppure è disattivata con `DISABLED_CONVERSIONS`.

**Funziona senza Internet?**
Sì. Internet serve solo per costruire l'immagine.
