#!/bin/bash
# Prepara una release dell'app Nextcloud per l'App Store (https://apps.nextcloud.com).
#   scripts/nextcloud-release.sh            crea dist/convertitore-<versione>.tar.gz e stampa la firma
#
# Serve la chiave privata dell'app in ~/.nextcloud/certificates/convertitore.key (MAI nel repository) e, per la
# firma del codice (appinfo/signature.json), il certificato convertitore.crt rilasciato da Nextcloud
# (https://github.com/nextcloud/app-certificate-requests). La firma del codice si fa con "occ integrity:sign-app"
# dentro un container Nextcloud: variabile NC_CONTAINER (predefinito: nessuna firma del codice).
# Poi: release su GitHub con l'archivio allegato e "Upload app release" sullo Store con link e firma.
set -euo pipefail
export COPYFILE_DISABLE=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERTS="${NC_CERTS:-$HOME/.nextcloud/certificates}"
KEY="$CERTS/convertitore.key"; CRT="$CERTS/convertitore.crt"
VER=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$ROOT/nextcloud-app/appinfo/info.xml")
OUT="$ROOT/dist/convertitore-$VER.tar.gz"
[ -f "$KEY" ] || { echo "Manca $KEY"; exit 1; }

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/convertitore"
tar --no-xattrs -C "$ROOT/nextcloud-app" --exclude .DS_Store -cf - . | tar -xf - -C "$STAGE/convertitore"

if [ -n "${NC_CONTAINER:-}" ] && [ -f "$CRT" ]; then
  # firma del codice: occ integrity:sign-app scrive appinfo/signature.json (la chiave resta nel container il meno possibile)
  docker cp "$STAGE/convertitore" "$NC_CONTAINER:/tmp/convertitore-sign"
  docker cp "$KEY" "$NC_CONTAINER:/tmp/convertitore-sign.key"; docker cp "$CRT" "$NC_CONTAINER:/tmp/convertitore-sign.crt"
  docker exec -u 0 "$NC_CONTAINER" chown -R 33:33 /tmp/convertitore-sign /tmp/convertitore-sign.key /tmp/convertitore-sign.crt
  docker exec -u 33 "$NC_CONTAINER" php /var/www/html/occ integrity:sign-app --path=/tmp/convertitore-sign \
    --privateKey=/tmp/convertitore-sign.key --certificate=/tmp/convertitore-sign.crt || true
  docker cp "$NC_CONTAINER:/tmp/convertitore-sign/appinfo/signature.json" "$STAGE/convertitore/appinfo/signature.json"
  docker exec -u 0 "$NC_CONTAINER" rm -rf /tmp/convertitore-sign /tmp/convertitore-sign.key /tmp/convertitore-sign.crt
  echo "Firma del codice: appinfo/signature.json"
else
  echo "(firma del codice saltata: servono NC_CONTAINER e $CRT)"
fi

mkdir -p "$ROOT/dist"
tar --no-xattrs -C "$STAGE" -czf "$OUT" convertitore
echo "Archivio: $OUT"
echo "Firma per lo Store:"
openssl dgst -sha512 -sign "$KEY" "$OUT" | openssl base64 -A; echo
