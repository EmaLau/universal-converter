#!/bin/sh
# Prepara le cartelle di lavoro (anche su un volume appena montato) e avvia il comando.
set -e
mkdir -p "${WORK_DIR:-/work}/home" "${TMPDIR:-/work/tmp}"
# Caratteri dell'utente (FONTS_DIR, predefinita /work/fonts): fontconfig li legge con la precedenza sui sostituti
FONTS="${FONTS_DIR:-/work/fonts}"
mkdir -p "$FONTS" 2>/dev/null || true
mkdir -p "$HOME/.config/fontconfig"
printf '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n<fontconfig><dir>%s</dir></fontconfig>\n' \
  "$FONTS" > "$HOME/.config/fontconfig/fonts.conf"
if [ -n "$(ls -A "$FONTS" 2>/dev/null)" ]; then fc-cache "$FONTS" >/dev/null 2>&1 || true; fi
exec "$@"
