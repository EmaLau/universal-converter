# Immagine usata da pdf_watcher.py per le conversioni. Se manca, lo script la costruisce da solo.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    xournalpp xvfb xauth libreoffice-nogui libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
    poppler-utils fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*
