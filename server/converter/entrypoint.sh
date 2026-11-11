#!/bin/sh
# Prepara le cartelle di lavoro (anche su un volume appena montato) e avvia il comando.
set -e
mkdir -p "${WORK_DIR:-/work}/home" "${TMPDIR:-/work/tmp}"
exec "$@"
