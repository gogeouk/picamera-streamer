#!/bin/bash
# Restart the streamer if it has stopped serving frames.
#
# Run as a systemd oneshot from picamera-monitor.timer. Output goes to the
# journal: journalctl -u picamera-monitor.service
#
# NOTE: the shebang must be the very first byte of this file. A leading blank
# line makes the kernel reject it with "Exec format error" (systemd 203/EXEC),
# which silently disabled this health check entirely for months.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$DIR/.env"
SERVICE="${SERVICE:-picamera.service}"

PORT=8000
SCHEME=http
CURL_OPTS=(-sf --max-time 10)

if [ -f "$ENV_FILE" ]; then
  env_port=$(sed -nE 's/^PORT=[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1/p' "$ENV_FILE" | head -1)
  [ -n "${env_port:-}" ] && PORT="$env_port"

  # KEYFILE set means the server is serving HTTPS, so probing http:// would
  # always fail (or always pass) and the check would be meaningless.
  if sed -nE 's/^KEYFILE=[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/p' "$ENV_FILE" | grep -q .; then
    SCHEME=https
    CURL_OPTS+=(-k)   # cert is issued for the public hostname, not localhost
  fi
fi

URL="$SCHEME://localhost:$PORT/current.jpg"

if curl "${CURL_OPTS[@]}" "$URL" -o /dev/null; then
  echo "$(date -Is): ok ($URL)"
  exit 0
fi

echo "$(date -Is): health check FAILED ($URL) — restarting $SERVICE"
systemctl restart "$SERVICE"
