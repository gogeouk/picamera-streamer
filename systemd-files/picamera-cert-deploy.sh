#!/bin/bash
# Certbot deploy hook: install a renewed certificate for the local streamer and
# push it to the peer Pi.
#
# Runs as root, because certbot does.
#
# History: the first version ran scp as root, which had no SSH key, so every
# renewal failed to reach the peer silently. The second (Aug 2026) borrowed the
# streamer user's key via sudo -u, which worked but meant the peer trusted that
# key with everything. Since Sep 2026 the hook has its own key, which the peer
# accepts only as the forced command cert-receive.sh.
#
# Install on the Pi that owns certbot:
#   sudo cp systemd-files/picamera-cert-deploy.sh \
#           /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
#   sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
#   sudo cp systemd-files/picamera-cert-deploy.conf.example \
#           /etc/default/picamera-cert-deploy   # then edit it
#
# Peer setup (once): a dedicated key and the peer's pinned host keys —
#   sudo mkdir -p /etc/picamera-cert-deploy && sudo chmod 700 /etc/picamera-cert-deploy
#   sudo ssh-keygen -t ed25519 -N '' -C cert-sync@<this-pi> -f /etc/picamera-cert-deploy/peer_ed25519
#   # on the peer, in ~/.ssh/authorized_keys:
#   #   restrict,command="/home/<user>/picamera-streamer/cert-receive.sh" <that .pub>
#   # and here, the peer's host keys as "[host]:port <type> <key>" lines in
#   #   /etc/picamera-cert-deploy/known_hosts
#
# Test without waiting for a renewal:
#   sudo /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh --check   # validate only
#   sudo /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh           # the real thing

set -uo pipefail

CONF=/etc/default/picamera-cert-deploy
# shellcheck disable=SC1090
[ -r "$CONF" ] && . "$CONF"

DOMAIN="${DOMAIN:-}"
LOCAL_USER="${LOCAL_USER:-lee}"
CERT_DIR="${CERT_DIR:-/etc/letsencrypt/live/$DOMAIN}"
DEST_DIR="${DEST_DIR:-/home/$LOCAL_USER/picamera-streamer/certificates}"
SERVICE="${SERVICE:-picamera.service}"
PEER_HOST="${PEER_HOST:-}"
PEER_PORT="${PEER_PORT:-22}"
PEER_USER="${PEER_USER:-$LOCAL_USER}"
PEER_DEST="${PEER_DEST:-$DEST_DIR}"
PEER_SERVICE="${PEER_SERVICE:-$SERVICE}"

status=0
log() { echo "$(date -Is) picamera-cert-deploy: $*"; logger -t picamera-cert-deploy -- "$*" 2>/dev/null || true; }
warn() { log "WARNING: $*"; status=1; }

[ -n "$DOMAIN" ] || { log "ERROR: DOMAIN not set (see $CONF)"; exit 1; }
[ -d "$CERT_DIR" ] || { log "ERROR: cert dir not found: $CERT_DIR"; exit 1; }

PEER_KEY="${PEER_KEY:-/etc/picamera-cert-deploy/peer_ed25519}"
PEER_KNOWN_HOSTS="${PEER_KNOWN_HOSTS:-/etc/picamera-cert-deploy/known_hosts}"

peer() {  # peer <check|install>
  tar -C "$DEST_DIR" -cf - fullchain.pem privkey.pem |
    ssh -i "$PEER_KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$PEER_KNOWN_HOSTS" \
        -p "$PEER_PORT" "$PEER_USER@$PEER_HOST" "$1"
}

# `picamera-cert-deploy.sh --check` validates the peer round trip with the
# certificate already installed here, and changes nothing on either Pi.
if [ "${1:-}" = "--check" ]; then
  [ -n "$PEER_HOST" ] || { log "no PEER_HOST configured"; exit 1; }
  peer check && log "peer check passed" || warn "peer check FAILED"
  exit $status
fi

# ── Local install ───────────────────────────────────────────────────────────
install -o "$LOCAL_USER" -g "$LOCAL_USER" -m 644 \
  "$CERT_DIR/fullchain.pem" "$DEST_DIR/fullchain.pem" || { log "ERROR: local fullchain install failed"; exit 1; }
install -o "$LOCAL_USER" -g "$LOCAL_USER" -m 600 \
  "$CERT_DIR/privkey.pem"   "$DEST_DIR/privkey.pem"   || { log "ERROR: local privkey install failed"; exit 1; }

expiry=$(openssl x509 -enddate -noout -in "$DEST_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2)
log "installed locally (expires $expiry)"

systemctl restart "$SERVICE" && log "restarted $SERVICE" || warn "could not restart $SERVICE"

# ── Peer sync ───────────────────────────────────────────────────────────────
# Uses a dedicated key that the peer accepts ONLY as a forced command
# (cert-receive.sh), and a pinned known_hosts file, so the peer's identity is
# checked and this key can do nothing but hand over a valid certificate. Runs as
# root with that key directly; the earlier version borrowed $LOCAL_USER's ordinary
# key, which the peer trusted with everything.
#
# Failures are reported loudly rather than aborting: the local Pi is already
# healthy, and a silent failure is what caused the original problem.
if [ -z "$PEER_HOST" ]; then
  log "no PEER_HOST configured — skipping peer sync"
  exit $status
fi

sync_peer() { peer install; }

if sync_peer; then
  log "synced to $PEER_USER@$PEER_HOST:$PEER_PORT and restarted $PEER_SERVICE"
else
  warn "PEER SYNC FAILED for $PEER_USER@$PEER_HOST:$PEER_PORT — that Pi is still on its old certificate and will go offline when it expires"
fi

exit $status
