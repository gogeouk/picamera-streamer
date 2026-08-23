#!/bin/bash
# Certbot deploy hook: install a renewed certificate for the local streamer and
# push it to the peer Pi.
#
# Runs as root, because certbot does.
#
# IMPORTANT: root has no SSH key on these Pis — the key lives in the streamer
# user's home directory. The previous version of this hook ran scp directly as
# root, so it had no credentials, failed every single renewal, and (because of
# `set -e`) aborted before reporting anything. The local Pi got its new cert and
# the peer silently stayed on a stale one until someone noticed it had expired.
# The peer transfer therefore drops to $LOCAL_USER via sudo -u and reuses that
# user's existing key.
#
# Install on the Pi that owns certbot:
#   sudo cp systemd-files/picamera-cert-deploy.sh \
#           /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
#   sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
#   sudo cp systemd-files/picamera-cert-deploy.conf.example \
#           /etc/default/picamera-cert-deploy   # then edit it
#
# Test without waiting for a renewal:
#   sudo /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh

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

# ── Local install ───────────────────────────────────────────────────────────
install -o "$LOCAL_USER" -g "$LOCAL_USER" -m 644 \
  "$CERT_DIR/fullchain.pem" "$DEST_DIR/fullchain.pem" || { log "ERROR: local fullchain install failed"; exit 1; }
install -o "$LOCAL_USER" -g "$LOCAL_USER" -m 600 \
  "$CERT_DIR/privkey.pem"   "$DEST_DIR/privkey.pem"   || { log "ERROR: local privkey install failed"; exit 1; }

expiry=$(openssl x509 -enddate -noout -in "$DEST_DIR/fullchain.pem" 2>/dev/null | cut -d= -f2)
log "installed locally (expires $expiry)"

systemctl restart "$SERVICE" && log "restarted $SERVICE" || warn "could not restart $SERVICE"

# ── Peer sync ───────────────────────────────────────────────────────────────
# Runs as $LOCAL_USER so it picks up that user's SSH key. Failures here are
# reported loudly rather than aborting: the local Pi is already healthy, and a
# silent failure is what caused this whole problem.
if [ -z "$PEER_HOST" ]; then
  log "no PEER_HOST configured — skipping peer sync"
  exit $status
fi

SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

sync_peer() {
  sudo -u "$LOCAL_USER" scp $SSH_OPTS -P "$PEER_PORT" \
      "$DEST_DIR/fullchain.pem" "$DEST_DIR/privkey.pem" \
      "$PEER_USER@$PEER_HOST:$PEER_DEST/" || return 1
  sudo -u "$LOCAL_USER" ssh $SSH_OPTS -p "$PEER_PORT" "$PEER_USER@$PEER_HOST" \
      "chmod 644 $PEER_DEST/fullchain.pem && chmod 600 $PEER_DEST/privkey.pem && sudo systemctl restart $PEER_SERVICE" || return 1
}

if sync_peer; then
  log "synced to $PEER_USER@$PEER_HOST:$PEER_PORT and restarted $PEER_SERVICE"
else
  warn "PEER SYNC FAILED for $PEER_USER@$PEER_HOST:$PEER_PORT — that Pi is still on its old certificate and will go offline when it expires"
fi

exit $status
