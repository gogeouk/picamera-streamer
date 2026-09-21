#!/bin/bash
# The only thing the certificate-sync key is allowed to do on the peer Pi.
#
# Both Pis serve the same DuckDNS hostname, so only one of them (geoone) can renew
# the certificate; its certbot deploy hook then sends the result here. Installed on
# the peer (geotwo) as a forced command, on the sync key only:
#   restrict,command="/home/lee/picamera-streamer/cert-receive.sh" ssh-ed25519 AAAA... cert-sync@geoone
#
# Until 2026-09-21 the hook used lee's ordinary key on geoone, which geotwo accepted
# with no restriction — so taking over one Pi meant owning both. Now a compromise of
# geoone can at most hand geotwo a certificate, and only one that is valid, matches
# its own private key, covers the same names as the one already installed, and is
# not older than it.
#
#   ssh ... check    < tar(fullchain.pem, privkey.pem)   validate only
#   ssh ... install  < tar(fullchain.pem, privkey.pem)   validate, install, restart
#
# NOTE: the shebang must stay the first byte of this file (see AGENTS.md).

set -u
DEST="${CERT_DEST:-/home/lee/picamera-streamer/certificates}"
SERVICE=picamera.service

fail() { echo "cert-receive: refused: $*" >&2; logger -t cert-receive "refused: $*"; exit 1; }

verb="${SSH_ORIGINAL_COMMAND:-}"
case "$verb" in check|install) ;; *) fail "unknown command '${verb:-<interactive login>}'";; esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Exactly two named members, from at most 64 KB of input. Naming them means tar
# cannot be talked into writing anywhere else.
head -c 65536 | tar -x -C "$tmp" --no-same-owner --no-same-permissions fullchain.pem privkey.pem 2>/dev/null \
  || fail "input is not a tar of fullchain.pem and privkey.pem"
[ "$(ls -A "$tmp" | wc -l)" -eq 2 ] || fail "unexpected files in input"

new="$tmp/fullchain.pem"; key="$tmp/privkey.pem"; cur="$DEST/fullchain.pem"

openssl x509 -in "$new" -noout 2>/dev/null || fail "fullchain.pem is not a certificate"
openssl x509 -in "$new" -noout -checkend 86400 >/dev/null || fail "certificate expired or expires within a day"

pub_cert=$(openssl x509 -in "$new" -noout -pubkey 2>/dev/null | openssl sha256)
pub_key=$(openssl pkey -in "$key" -pubout 2>/dev/null | openssl sha256)
[ -n "$pub_key" ] && [ "$pub_cert" = "$pub_key" ] || fail "private key does not match certificate"

names() { openssl x509 -in "$1" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' '; }
if [ -f "$cur" ]; then
  [ "$(names "$new")" = "$(names "$cur")" ] || fail "names differ from the installed certificate: $(names "$new")"
  new_end=$(date -d "$(openssl x509 -in "$new" -noout -enddate | cut -d= -f2)" +%s)
  cur_end=$(date -d "$(openssl x509 -in "$cur" -noout -enddate | cut -d= -f2)" +%s)
  [ "$new_end" -ge "$cur_end" ] || fail "older than the installed certificate"
fi

expiry=$(openssl x509 -in "$new" -noout -enddate | cut -d= -f2)
if [ "$verb" = check ]; then
  echo "cert-receive: ok, would install (expires $expiry)"
  exit 0
fi

# Same directory, then rename: the streamer never sees a half-written file.
install -m 644 "$new" "$DEST/.fullchain.pem.new" && install -m 600 "$key" "$DEST/.privkey.pem.new" \
  && mv -f "$DEST/.fullchain.pem.new" "$DEST/fullchain.pem" && mv -f "$DEST/.privkey.pem.new" "$DEST/privkey.pem" \
  || fail "could not write to $DEST"
logger -t cert-receive "installed certificate expiring $expiry"
sudo systemctl restart "$SERVICE" || fail "installed, but could not restart $SERVICE"
echo "cert-receive: installed (expires $expiry) and restarted $SERVICE"
