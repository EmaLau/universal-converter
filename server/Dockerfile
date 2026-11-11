# Universal Converter: pagina web e API sulla porta 8080.
#   docker build -t universal-converter server/
#   docker run -p 8080:8080 universal-converter
# UID/GID dell'utente che esegue il servizio (proprietario di /work): --build-arg UID=... GID=...
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-fastapi python3-uvicorn python3-img2pdf \
      libreoffice-nogui libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui libreoffice-draw-nogui \
      ffmpeg imagemagick libheif-plugin-libde265 libheif-plugin-x265 libheif-plugin-aomenc libheif-plugin-dav1d \
      libraw-bin librsvg2-bin poppler-utils ghostscript pandoc calibre \
      libarchive-tools 7zip xournalpp xvfb xauth \
      fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core \
      ca-certificates tini \
    && pip3 install --no-cache-dir --break-system-packages pdf2docx==0.5.8 python-multipart==0.0.20 \
    && rm -rf /var/lib/apt/lists/* /root/.cache

ARG UID=1000
ARG GID=1000
RUN groupadd -g "$GID" converter 2>/dev/null || true \
    && useradd -u "$UID" -g "$GID" -M -d /work/home -s /usr/sbin/nologin converter 2>/dev/null || true \
    && mkdir -p /work && chown "$UID:$GID" /work

COPY converter /app/converter
COPY selftest.py /app/selftest.py
# Documentazione: dal Markdown alla pagina /docs
COPY docs /app/docs
RUN pandoc /app/docs/documentazione.md --standalone --section-divs --toc --toc-depth=2 \
      --template /app/docs/template.html -H /app/docs/style.html -o /app/converter/static/docs.html

ENV WORK_DIR=/work HOME=/work/home TMPDIR=/work/tmp QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox
USER ${UID}:${GID}
WORKDIR /app
VOLUME /work
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5)"
ENTRYPOINT ["/usr/bin/tini", "--", "/app/converter/entrypoint.sh"]
CMD ["python3", "-m", "uvicorn", "--factory", "converter.app:create_app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
