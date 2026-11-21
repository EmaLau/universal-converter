/* Universal Converter: interfaccia in italiano o in inglese.
   Le pagine sono scritte in italiano; se la lingua scelta e' l'inglese, ogni testo che compare nella pagina
   (anche quelli creati dal JavaScript o arrivati dall'API, come i nomi degli strumenti PDF) viene tradotto con
   questo dizionario. La lingua parte da quella del browser e si cambia con il selettore IT / EN (ricordato in
   localStorage). Alle richieste al server si aggiunge Accept-Language, cosi' anche errori, passaggi e note dei
   lavori arrivano nella lingua giusta. Stesso meccanismo di Plico. */
"use strict";
const UC_I18N = (() => {
  const EN = {
    // intestazione e home
    "Convertitore": "Converter", "Documentazione": "Documentation", "Documentazione API": "API docs",
    "Tutti gli strumenti": "All tools", "🔒 Tutto in locale": "🔒 Runs locally",
    "I file vengono elaborati su questo server e cancellati dopo qualche ora": "Files are processed on this server and deleted after a few hours",
    "Converti qualsiasi file": "Convert any file",
    "Documenti, fogli di calcolo, presentazioni, immagini, audio, video, sottotitoli, ebook, dati, font e archivi, più gli strumenti per i PDF. Niente cloud: tutto avviene sul tuo server.":
      "Documents, spreadsheets, presentations, images, audio, video, subtitles, ebooks, data, fonts and archives, plus PDF tools. No cloud: everything happens on your own server.",
    "Tutti i formati supportati": "All supported formats", "Il convertitore non risponde.": "The converter is not responding.",
    "Tutti": "All", "Qualsiasi formato": "Any format", "Carica un file e scegli in cosa convertirlo": "Upload a file and choose what to convert it to",
    // categorie (dall'API)
    "Documento": "Document", "Foglio di calcolo": "Spreadsheet", "Presentazione": "Presentation", "Disegno": "Drawing",
    "Immagine": "Image", "Audio": "Audio", "Video": "Video", "Sottotitoli": "Subtitles", "Ebook": "Ebook",
    "Dati": "Data", "Font": "Fonts", "Archivio": "Archive",
    // strumenti in evidenza
    "PDF in Word": "PDF to Word", "Rendi modificabile un PDF": "Make a PDF editable",
    "PDF in PowerPoint": "PDF to PowerPoint", "Slide modificabili": "Editable slides",
    "Una cartella": "A folder",
    "oppure trascinali qui (anche intere cartelle)": "or drag them here (whole folders too)",
    "Tabelle PDF in Excel": "PDF tables to Excel", "Ogni tabella in un foglio": "Each table in a sheet",
    "Video in sottotitoli": "Video to subtitles", "Trascrizione SRT con Whisper": "SRT transcription with Whisper",
    "Audio in testo": "Audio to text", "Trascrizione con Whisper": "Transcription with Whisper",
    "Immagini da un PDF": "Images from a PDF", "Le immagini originali in uno ZIP, in Plico": "The original images in a ZIP, in Plico",
    "Word in PDF": "Word to PDF", "Excel in PDF": "Excel to PDF", "PowerPoint in PDF": "PowerPoint to PDF",
    "Immagini in PDF": "Images to PDF", "PDF in JPG": "PDF to JPG", "Una immagine per pagina": "One image per page",
    "HEIC in JPG": "HEIC to JPG", "Foto di iPhone": "iPhone photos", "Immagine in PNG": "Image to PNG",
    "Qualsiasi immagine": "Any image", "Immagine in WEBP": "Image to WEBP", "Più leggera per il web": "Lighter for the web",
    "RAW in JPG": "RAW to JPG", "Video in MP4": "Video to MP4", "Video in MP3": "Video to MP3", "Estrai l'audio": "Extract the audio",
    "Video in GIF": "Video to GIF", "Primi 60 secondi": "First 60 seconds", "Audio in MP3": "Audio to MP3",
    "EPUB in PDF": "EPUB to PDF", "Ebook da stampare": "Ebooks to print", "Ebook per Kindle": "Ebooks for Kindle",
    "EPUB in AZW3": "EPUB to AZW3", "Markdown in PDF": "Markdown to PDF", "Anche HTML, LaTeX, Jupyter": "Also HTML, LaTeX, Jupyter",
    "Word in Markdown": "Word to Markdown", "Archivio in ZIP": "Archive to ZIP", "Xournal++ in PDF": "Xournal++ to PDF",
    "Appunti .xopp": ".xopp notes", "PDF in SVG": "PDF to SVG", "Pagine vettoriali": "Vector pages",
    "Markdown in PowerPoint": "Markdown to PowerPoint", "Una slide per titolo": "One slide per heading",
    "JSON in Excel": "JSON to Excel", "Anche YAML e TOML": "Also YAML and TOML", "Excel in JSON": "Excel to JSON",
    "Sottotitoli in SRT": "Subtitles to SRT", "Font per il web": "Web fonts", "TTF e OTF in WOFF2": "TTF and OTF to WOFF2",
    "EPS in PDF": "EPS to PDF", "PostScript ed EPS": "PostScript and EPS", "Archivio in TAR.ZST": "Archive to TAR.ZST",
    "Compressione moderna": "Modern compression", "Testo": "Text",
    // strumenti PDF (dall'API)
    "Unisci PDF": "Merge PDF", "Più PDF in uno solo, nell'ordine scelto": "Several PDFs into one, in the chosen order", "Unisci": "Merge",
    "Dividi PDF": "Split PDF", "Un PDF per pagina o per intervallo": "One PDF per page or per range", "Dividi": "Split",
    "Estrai pagine": "Extract pages", "Un nuovo PDF con le pagine scelte": "A new PDF with the chosen pages", "Estrai": "Extract",
    "Togli pagine": "Remove pages", "Elimina le pagine che non servono": "Delete the pages you don't need", "Togli le pagine": "Remove the pages",
    "Ruota PDF": "Rotate PDF", "Raddrizza tutte le pagine o solo alcune": "Straighten all pages or just some", "Ruota": "Rotate",
    "Comprimi PDF": "Compress PDF", "Riduci il peso ricomprimendo le immagini": "Make the file smaller by recompressing the images", "Comprimi": "Compress",
    "OCR PDF": "OCR PDF", "Rendi ricercabile il testo delle scansioni": "Make the text of scans searchable", "Riconosci il testo": "Recognise the text",
    "Pagine": "Pages", "Intervalli (vuoto = una pagina per file)": "Ranges (empty = one page per file)", "Pagine (vuoto = tutte)": "Pages (empty = all)",
    "Rotazione": "Rotation", "90° in senso orario": "90° clockwise", "180°": "180°", "90° in senso antiorario": "90° counter-clockwise",
    "Compressione": "Compression", "Bassa (qualità di stampa)": "Low (print quality)", "Media (consigliata)": "Medium (recommended)",
    "Alta (file più piccolo)": "High (smallest file)", "Lingue": "Languages",
    "Rifai l'OCR anche sulle pagine che hanno già testo": "Redo OCR also on pages that already have text",
    "Altri strumenti PDF in Plico": "More PDF tools in Plico",
    "Firma, oscura, proteggi, filigrana, PDF/A, confronta e altro": "Sign, redact, protect, watermark, PDF/A, compare and more",
    // area di lavoro
    "← Tutti gli strumenti": "← All tools", "Converti file": "Convert files", "Seleziona i file": "Select files",
    "oppure trascinali qui": "or drop them here",
    "Carica uno o più file, poi scegli il formato di arrivo per ciascuno.": "Upload one or more files, then choose the target format for each.",
    "Converti tutti in": "Convert all to", "Scarica tutti": "Download all", "Converti": "Convert", "(diversi)": "(mixed)",
    "Formato di arrivo": "Target format", "Qui servono file PDF": "PDF files are needed here", "Pronto": "Ready",
    "Scarica": "Download", "Riprova": "Retry", "Rimuovi": "Remove", "Sposta su": "Move up", "Sposta giù": "Move down",
    "Conversione…": "Converting…", "In coda…": "Queued…", "connessione interrotta": "connection lost",
    // pagina admin
    "Chiavi API": "API keys", "Convertitore · Chiavi API": "Converter · API keys", "Esci": "Log out",
    "Le chiavi servono agli script e agli altri servizi (app Nextcloud, Plico, curl, Comandi rapidi di iPhone) per usare l'API. Ognuna ha i suoi permessi e si può revocare in ogni momento. La pagina web non ne ha bisogno.":
      "Keys let scripts and other services (Nextcloud app, Plico, curl, iPhone Shortcuts) use the API. Each one has its own permissions and can be revoked at any time. The web page doesn't need one.",
    "Area admin disattivata": "Admin area disabled",
    "Per attivarla imposta la variabile": "To enable it set the variable", ", oppure scrivi la password nel file": ", or write the password in the file",
    "della cartella dei dati (": "in the data folder (", ", predefinita": ", default", "), poi riavvia il servizio.": "), then restart the service.",
    "Accedi": "Log in", "Password admin": "Admin password", "Nuova chiave": "New key",
    "Nome (per ricordarti chi la usa)": "Name (to remember who uses it)", "es. App Nextcloud": "e.g. Nextcloud app",
    "Crea chiave": "Create key", "Tutti i permessi": "All permissions", "Accesso all'area admin": "Access to the admin area",
    "Password per entrare in questa pagina": "Password to enter this page", "Chiave creata: copiala adesso": "Key created: copy it now",
    "Non verrà più mostrata: sul server resta solo una sua impronta. Se la perdi, revocala e creane un'altra.":
      "It won't be shown again: the server keeps only a fingerprint of it. If you lose it, revoke it and create another one.",
    "Copia": "Copy", "Copiata": "Copied", "Esempio:": "Example:", "Chiavi attive": "Active keys",
    "Chiave obbligatoria per le API": "API key required", "Revoca": "Revoke", "Conferma revoca": "Confirm revoke",
    "Nessuna chiave per ora.": "No keys yet.", "Scegli almeno un permesso": "Choose at least one permission",
    "Formati e piani di conversione": "Formats and conversion plans", "Avviare conversioni e strumenti PDF": "Start conversions and PDF tools",
    "Stato, download e cancellazione dei lavori": "Job status, download and deletion",
    "Lavori contemporanei": "Concurrent jobs", "MB al giorno": "MB per day", "senza limite": "no limit",
    "Apri in Plico": "Open in Plico",
    // anteprima, cronologia, indirizzi, incolla, app installabile (2.4)
    "⤓ Installa": "⤓ Install", "Conversioni recenti": "Recent conversions", "Svuota la cronologia": "Clear history",
    "Solo in questo browser. I risultati restano sul server per qualche ora.": "Only in this browser. Results stay on the server for a few hours.",
    "oppure un indirizzo web (https://…)": "or a web address (https://…)", "Indirizzo del file": "File address", "Aggiungi": "Add",
    "Puoi anche incollare (⌘V / Ctrl+V) un file, un'immagine, un testo o un indirizzo.": "You can also paste (⌘V / Ctrl+V) a file, an image, some text or an address.",
    "Download dall'indirizzo…": "Downloading from the address…", "Anteprima": "Preview", "Chiudi anteprima": "Close preview",
    "Preparazione dell'anteprima…": "Preparing the preview…", "Anteprima non disponibile per questo file": "No preview for this file",
    // opzioni di conversione e preset
    "Preset": "Preset", "— nessuno —": "— none —", "Predefiniti": "Built-in", "I miei preset": "My presets",
    "Nome del preset": "Preset name", "Salva": "Save", "Annulla": "Cancel", "Salva come preset": "Save as preset",
    "Elimina il preset": "Delete preset", "Opzioni": "Options",
    "Qualità (1-100)": "Quality (1-100)", "Lato lungo massimo (pixel)": "Longest side (pixels)",
    "Inizio (es. 0:30)": "Start (e.g. 0:30)", "Fine (es. 1:45)": "End (e.g. 1:45)",
    "Risoluzione massima": "Maximum resolution", "Originale": "Original", "Qualità del video": "Video quality",
    "Predefinita": "Default", "Alta (file più grande)": "High (larger file)", "Media": "Medium", "Bassa (file più piccolo)": "Low (smaller file)",
    "Bitrate dell'audio": "Audio bitrate", "Predefinito": "Default", "Audio mono (un solo canale)": "Mono audio (one channel)",
    "Risoluzione delle pagine": "Page resolution", "150 DPI (predefinita)": "150 DPI (default)", "72 DPI (schermo)": "72 DPI (screen)",
    "300 DPI (stampa)": "300 DPI (print)", "Pagine (es. 2 oppure 3-5)": "Pages (e.g. 2 or 3-5)", "tutte": "all",
    "Togli i metadati (data, posizione GPS, fotocamera)": "Remove metadata (date, GPS location, camera)",
    "Impaginazione": "Layout", "Modificabile (predefinita)": "Editable (default)",
    "Identica all'originale (pagine come immagini, testo non modificabile)": "Identical to the original (pages as images, text not editable)",
    "Word identico al PDF": "Word identical to the PDF",
    "Lingua del parlato": "Spoken language", "Riconoscimento automatico": "Detect automatically", "Italiano": "Italian",
    "Inglese": "English", "Francese": "French", "Tedesco": "German", "Spagnolo": "Spanish", "Portoghese": "Portuguese",
    "Olandese": "Dutch", "Polacco": "Polish", "Rumeno": "Romanian", "Russo": "Russian", "Ucraino": "Ukrainian",
    "Arabo": "Arabic", "Cinese": "Chinese", "Giapponese": "Japanese",
    "Foto per il web": "Photos for the web", "Foto per email": "Photos for email", "Video per WhatsApp": "Video for WhatsApp",
    "Video leggero (480p)": "Light video (480p)", "Audio per podcast": "Audio for podcasts",
    "Primi 30 secondi in MP3": "First 30 seconds as MP3", "Pagine PDF per la stampa": "PDF pages for printing",
    "Attivo: ogni chiamata fatta fuori dalla pagina web deve avere una chiave. La pagina web continua a funzionare.":
      "On: every call made outside the web page needs a key. The web page keeps working.",
    "Disattivo: le chiamate senza chiave sono accettate. Le chiavi limitano comunque cosa può fare ogni script.":
      "Off: calls without a key are accepted. Keys still limit what each script can do.",
    "Attiva: per entrare serve la password admin.": "On: the admin password is needed to enter.",
    "Disattiva:": "Off:",
    "chiunque raggiunga il servizio può creare, modificare e revocare le chiavi. Con la password spenta anche l'obbligo della chiave protegge poco, perché chiunque può crearsene una.":
      "anyone who can reach the service can create, change and revoke keys. With the password off, requiring a key protects little, because anyone can create one.",
    "Disattiva, e non c'è nessuna password impostata: per riattivarla imposta CONVERTER_ADMIN_PASSWORD o il file admin-password e riavvia.":
      "Off, and no password is set: to turn it back on set CONVERTER_ADMIN_PASSWORD or the admin-password file and restart.",
  };
  const RX = [
    [/^Converti (\d+) file$/, "Convert $1 files"],
    [/^(.+) (\d+) PDF$/, m => tr(m[1]) + " " + m[2] + " PDFs"],
    [/^(.+) \*$/, m => tr(m[1]) + " *"],
    [/^(.+) → ([A-Z0-9.]+)$/, m => tr(m[1]) + " → " + m[2]],
    [/^(.+)\. Usa le frecce per cambiare l'ordine\.$/, m => tr(m[1]) + ". Use the arrows to change the order."],
    [/^Formato \.(.+) non supportato$/, "Format .$1 is not supported"],
    [/^([A-Z0-9.]+) \(stesso formato\)$/, "$1 (same format)"],
    [/^Ogni file in (.+)$/, "Every file to $1"],
    [/^Errore: (.*)$/s, "Error: $1"], [/^Errore (\d+)$/, "Error $1"],
    [/^Pronto: (.*)$/s, "Ready: $1"], [/^Caricamento (\d+)%$/, "Uploading $1%"],
    [/^In coda \(posizione (\d+)\)…$/, "Queued (position $1)…"],
    [/^file troppo grande \(massimo (.+)\)$/, "file too large (maximum $1)"],
    [/^I file vengono elaborati su questo server e cancellati dopo (\d+) ore$/, "Files are processed on this server and deleted after $1 hours"],
    [/^Oggi: (.+) MB · in corso: (\d+)$/, "Today: $1 MB · in progress: $2"],
    [/^Creata (.+) · ultimo uso: mai$/, "Created $1 · last used: never"],
    [/^Creata (.+) · ultimo uso: (.+)$/, "Created $1 · last used: $2"],
    [/^(.+) · Convertitore$/, m => tr(m[1]) + " · Converter"],
    [/^Solo in questo browser\. I risultati restano sul server per ([\d.]+) ore\.$/, "Only in this browser. Results stay on the server for $1 hours."],
  ];

  let saved = null;
  try { saved = localStorage.getItem("uc-lang"); } catch {}
  const lang = saved === "it" || saved === "en" ? saved : ((navigator.language || "en").toLowerCase().startsWith("it") ? "it" : "en");

  function tr(s) {
    if (lang === "it" || !s) return s;
    const t = s.trim();
    if (!t) return s;
    let out = EN[t];
    if (out === undefined) {
      for (const [rx, rep] of RX) {
        const m = t.match(rx);
        if (m) { out = typeof rep === "function" ? rep(m) : t.replace(rx, rep); break; }
      }
    }
    if (out === undefined) return s;
    return s.slice(0, s.indexOf(t[0])) + out + s.slice(s.lastIndexOf(t[t.length - 1]) + 1);
  }

  const ATTRS = ["placeholder", "title", "aria-label", "label"];
  function translate(node) {
    if (node.nodeType === 3) {
      const v = tr(node.data);
      if (v !== node.data) node.data = v;
      return;
    }
    if (node.nodeType !== 1 || node.tagName === "SCRIPT" || node.tagName === "STYLE" || node.tagName === "CODE" || node.getAttribute("translate") === "no") return;
    for (const a of ATTRS) if (node.hasAttribute(a)) { const v = tr(node.getAttribute(a)); if (v !== node.getAttribute(a)) node.setAttribute(a, v); }
    for (const c of node.childNodes) translate(c);
  }

  if (lang === "en") {
    document.documentElement.lang = "en";
    new MutationObserver(list => {
      for (const m of list) {
        if (m.type === "characterData") translate(m.target);
        else if (m.type === "attributes") translate(m.target);
        else m.addedNodes.forEach(translate);
      }
    }).observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
    document.addEventListener("DOMContentLoaded", () => { translate(document.documentElement); document.title = tr(document.title); });
  }

  // la lingua anche nelle richieste al server, per errori, passaggi e note dei lavori
  const _fetch = window.fetch.bind(window);
  window.fetch = (url, opt = {}) => {
    const headers = new Headers(opt.headers || {});
    if (!headers.has("Accept-Language")) headers.set("Accept-Language", lang);
    return _fetch(url, {...opt, headers});
  };
  const _send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) { try { this.setRequestHeader("Accept-Language", lang); } catch {} return _send.call(this, body); };

  function set(l) { try { localStorage.setItem("uc-lang", l); } catch {} location.reload(); }

  // selettore IT / EN, in qualsiasi elemento con data-lang-switch; link alla documentazione nella stessa lingua
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-lang-switch]").forEach(el => {
      el.innerHTML = ["it", "en"].map(l => `<button type="button" data-l="${l}" class="${l === lang ? "on" : ""}" aria-pressed="${l === lang}">${l.toUpperCase()}</button>`).join("");
      el.onclick = e => { const b = e.target.closest("button"); if (b && b.dataset.l !== lang) set(b.dataset.l); };
    });
    document.querySelectorAll('a[href="docs"]').forEach(a => { a.href = "docs?lang=" + lang; });
  });

  return {lang, tr, set};
})();
