#!/bin/bash
# Prepara una release dell'app Nextcloud per l'App Store (https://apps.nextcloud.com).
#   scripts/nextcloud-release.sh            crea dist/universal_converter-<versione>.tar.gz e stampa la firma
#
# Serve la chiave privata dell'app in ~/.nextcloud/certificates/universal_converter.key (MAI nel repository) e, per la
# firma del codice (appinfo/signature.json), il certificato universal_converter.crt rilasciato da Nextcloud
# (https://github.com/nextcloud/app-certificate-requests). La firma del codice si fa con "occ integrity:sign-app"
# dentro un container Nextcloud: variabile NC_CONTAINER (predefinito: nessuna firma del codice).
# Poi: release su GitHub con l'archivio allegato e "Upload app release" sullo Store con link e firma.
set -euo pipefail
export COPYFILE_DISABLE=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERTS="${NC_CERTS:-$HOME/.nextcloud/certificates}"
KEY="$CERTS/universal_converter.key"; CRT="$CERTS/universal_converter.crt"
VER=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$ROOT/nextcloud-app/appinfo/info.xml")
OUT="$ROOT/dist/universal_converter-$VER.tar.gz"
[ -f "$KEY" ] || { echo "Manca $KEY"; exit 1; }

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/universal_converter"
tar --no-xattrs -C "$ROOT/nextcloud-app" --exclude .DS_Store -cf - . | tar -xf - -C "$STAGE/universal_converter"

if [ -n "${NC_CONTAINER:-}" ] && [ -f "$CRT" ]; then
  # firma del codice: occ integrity:sign-app scrive appinfo/signature.json (la chiave resta nel container il meno possibile)
  docker cp "$STAGE/universal_converter" "$NC_CONTAINER:/tmp/universal_converter-sign"
  docker cp "$KEY" "$NC_CONTAINER:/tmp/universal_converter-sign.key"; docker cp "$CRT" "$NC_CONTAINER:/tmp/universal_converter-sign.crt"
  docker exec -u 0 "$NC_CONTAINER" chown -R www-data:www-data /tmp/universal_converter-sign /tmp/universal_converter-sign.key /tmp/universal_converter-sign.crt
  docker exec -u www-data "$NC_CONTAINER" php /var/www/html/occ integrity:sign-app --path=/tmp/universal_converter-sign \
    --privateKey=/tmp/universal_converter-sign.key --certificate=/tmp/universal_converter-sign.crt || true
  docker cp "$NC_CONTAINER:/tmp/universal_converter-sign/appinfo/signature.json" "$STAGE/universal_converter/appinfo/signature.json"
  docker exec -u 0 "$NC_CONTAINER" rm -rf /tmp/universal_converter-sign /tmp/universal_converter-sign.key /tmp/universal_converter-sign.crt
  echo "Firma del codice: appinfo/signature.json"
else
  echo "(firma del codice saltata: servono NC_CONTAINER e $CRT)"
fi

mkdir -p "$ROOT/dist"
tar --no-xattrs -C "$STAGE" -czf "$OUT" universal_converter
echo "Archivio: $OUT"
echo "Firma per lo Store:"
openssl dgst -sha512 -sign "$KEY" "$OUT" | openssl base64 -A; echo
