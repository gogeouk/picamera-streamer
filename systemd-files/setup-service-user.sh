#!/bin/bash
# Move picamera.service to its own unprivileged user. Idempotent; run with sudo.
# Does NOT restart the service: check the output, then `systemctl restart picamera`.
#
# NOTE: the shebang must stay the first byte of this file (see AGENTS.md).
set -euo pipefail

OWNER="${OWNER:-lee}"
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
APP="$HOME_DIR/picamera-streamer"
KEY="$APP/certificates/privkey.pem"

id picamera >/dev/null 2>&1 || useradd --system --user-group --no-create-home \
  --home-dir /nonexistent --shell /usr/sbin/nologin picamera
usermod -aG video picamera

# The service must pass through the owner's home to reach the streamer, so the home
# becomes 711. First close everything else in it to other users, so passing through
# reaches the streamer and nothing more (duckdns.sh, for one, holds a token).
find "$HOME_DIR" -mindepth 1 -maxdepth 1 ! -name picamera-streamer -exec chmod o-rwx {} +
chmod 711 "$HOME_DIR"

# TLS key: owner read/write, the service's group read.
chgrp picamera "$KEY"
chmod 640 "$KEY"

install -D -m 644 "$APP/systemd-files/picamera-user.conf" /etc/systemd/system/picamera.service.d/user.conf
systemctl daemon-reload

fail=0
for f in "$APP/picamera.py" "$APP/tools/getenv.py" "$APP/.env" "$APP/certificates/fullchain.pem" "$KEY"; do
  sudo -u picamera test -r "$f" || { echo "picamera CANNOT read $f"; fail=1; }
done
sudo -u picamera test -r "$HOME_DIR/.ssh/authorized_keys" 2>/dev/null && { echo "picamera CAN read .ssh - wrong"; fail=1; }
[ -e "$HOME_DIR/duckdns/duckdns.sh" ] && sudo -u picamera test -r "$HOME_DIR/duckdns/duckdns.sh" && { echo "picamera CAN read duckdns.sh - wrong"; fail=1; }
[ $fail -eq 0 ] && echo "ready: picamera can read the streamer and nothing else checked; restart picamera.service to switch"
exit $fail
