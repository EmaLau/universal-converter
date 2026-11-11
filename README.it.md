# Universal Converter

🇬🇧 [English](README.md) · 🇮🇹 **Italiano**

**Un convertitore di file self-hosted, in stile iLovePDF.** Documenti, fogli di calcolo, presentazioni, immagini, audio, video, sottotitoli, ebook, dati, font e archivi: circa **200 formati** e oltre **3.000 combinazioni**, tutto sul tuo server. I file non escono dalla tua rete e vengono cancellati da soli dopo qualche ora.

![Docker](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Nextcloud](https://img.shields.io/badge/Nextcloud-30--36-0082C9?logo=nextcloud&logoColor=white)
![Licenza](https://img.shields.io/badge/licenza-AGPL--3.0-blue)

## Funzionalità

- **Pagina web** con strumenti pronti ("Word in PDF", "HEIC in JPG", "JSON in Excel"…), trascinamento e conversione di più file insieme.
- **Conversioni a catena**: se non esiste un programma che converte direttamente, il server trova il percorso più breve. Markdown → PDF diventa Pandoc + LibreOffice, JSON → Excel diventa JSON → CSV → XLSX.
- **Veloce dove si può**: i video già compatibili vengono copiati senza ricodifica, in pochi secondi.
- **API JSON** per script e altre applicazioni.
- **App Nextcloud** (facoltativa): tasto destro su un file → **Converti in ▸ formato**, e il risultato appare accanto all'originale.
- **PDF automatici** (facoltativi) accanto agli appunti Xournal++ e ai documenti Office in Nextcloud.
- **Robusto**: coda con limite di conversioni contemporanee, tempi massimi, limite di dimensione sui file creati, pulizia automatica.

| Categoria | Alcuni formati |
|---|---|
| Documenti | PDF, DOCX, ODT, RTF, Markdown, HTML, LaTeX, AsciiDoc, Typst, Pages, Xournal++ |
| Fogli di calcolo e presentazioni | XLSX, ODS, CSV, Numbers, PPTX, ODP, Keynote |
| Immagini e disegni | JPG, PNG, WEBP, HEIC, AVIF, SVG, EPS, PSD, RAW delle fotocamere, CorelDRAW, Visio |
| Audio e video | MP3, FLAC, WAV, OPUS, MP4, MKV, MOV, WEBM, GIF |
| Altro | sottotitoli (SRT, VTT, ASS), ebook (EPUB, MOBI, AZW3, CBR), dati (JSON, YAML, TOML), font (TTF, OTF, WOFF2), archivi (ZIP, 7Z, RAR, TAR.ZST, ISO) |

## Avvio rapido

Serve Docker con Docker Compose.

```bash
git clone https://github.com/EmaLau/universal-converter.git
cd universal-converter
docker compose up -d --build
```

Apri <http://localhost:8080>. La documentazione completa è su <http://localhost:8080/docs>.

La prima build scarica LibreOffice, FFmpeg, Calibre e gli altri programmi (circa 500 MB): richiede qualche minuto. Le build successive sono quasi istantanee.

Per verificare che tutte le conversioni funzionino:

```bash
docker compose exec converter python3 /app/selftest.py
```

> **Nota sulla sicurezza.** Il servizio non ha login e di base risponde solo su `127.0.0.1`. Aprilo alla rete solo se è fidata (casa, VPN), oppure mettilo dietro un reverse proxy con autenticazione. Non esporlo direttamente su Internet.

## Configurazione

Copia `.env.example` in `.env` e modifica quello che ti serve. Le opzioni principali:

| Variabile | Predefinito | Descrizione |
|---|---|---|
| `CONVERTER_BIND` / `CONVERTER_PORT` | `127.0.0.1` / `8080` | Dove pubblicare il servizio (`0.0.0.0` per tutta la rete) |
| `MAX_PARALLEL` | `2` | Conversioni contemporanee |
| `RETAIN_HOURS` | `6` | Dopo quante ore si cancellano i risultati |
| `MAX_UPLOAD_GB` | `20` | Dimensione massima di un file caricato |
| `MAX_OUTPUT_GB` | `50` | Dimensione massima di ogni file creato durante una conversione |
| `DISABLED_CONVERSIONS` | vuoto | Conversioni da nascondere, es. `heic>avif,pdf>epub` |

L'elenco completo è in [`.env.example`](.env.example) e nella [documentazione](server/docs/documentazione.md#configurazione).

## API in breve

```bash
# carica un file e scegli il formato
id=$(curl -s -F file=@relazione.docx -F target=pdf http://localhost:8080/api/jobs | jq -r .id)

# controlla lo stato: queued, running, done o error
curl -s http://localhost:8080/api/jobs/$id

# scarica il risultato
curl -OJ http://localhost:8080/api/jobs/$id/download
```

Altri endpoint: `GET /api/formats` (formati supportati), `GET /api/plan/{da}/{a}` (passaggi previsti), `DELETE /api/jobs/{id}` (cancella subito), `GET /healthz`. I dettagli sono nella [documentazione dell'API](server/docs/documentazione.md#api).

## Nextcloud

```bash
cp -r nextcloud-app /percorso/nextcloud/custom_apps/convertitore
occ app:enable convertitore
occ config:app:set convertitore converter_url --value=http://indirizzo-del-convertitore:8080
```

L'indirizzo deve essere raggiungibile dal server Nextcloud. Installazione e funzionamento sono spiegati nella [documentazione](server/docs/documentazione.md#integrazione-con-nextcloud), insieme ai [PDF automatici](server/docs/documentazione.md#pdf-automatici-per-nextcloud).

## Struttura

```
server/            servizio web (FastAPI) e Dockerfile
  converter/       codice: API, coda dei lavori, grafo delle conversioni, convertitori
  docs/            documentazione completa (diventa la pagina /docs)
  tests/           test con pytest
  selftest.py      prova vera di tutte le conversioni
nextcloud-app/     app Nextcloud "Converti in"
pdf-watcher/       PDF automatici per Nextcloud
```

## Sviluppo

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

Per aggiungere un formato basta una funzione in `tools.py` e una riga in `graph.py`: menu, percorsi a catena e app Nextcloud si aggiornano da soli. La guida passo passo è nella sezione [Sviluppo](server/docs/documentazione.md#sviluppo).

## Documentazione

La [documentazione completa](server/docs/documentazione.md) copre installazione, configurazione, uso, API, funzionamento interno, Nextcloud, sicurezza, manutenzione, problemi noti e domande frequenti. Ogni server la mostra anche su `/docs`.

## Licenza

[GNU Affero General Public License v3.0](LICENSE). Puoi usare, modificare e ridistribuire il progetto liberamente. Se lo modifichi e lo offri come servizio in rete, devi rendere disponibile anche il codice sorgente delle tue modifiche.
