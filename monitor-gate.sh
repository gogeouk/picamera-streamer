#!/bin/bash
# The only thing the camera dashboard's SSH key is allowed to run.
#
# Installed as a forced command in ~/.ssh/authorized_keys, on the dashboard's own key:
#   restrict,command="/home/lee/picamera-streamer/monitor-gate.sh" ssh-ed25519 AAAA... picamera-monitor
#
# `restrict` turns off port forwarding, agent forwarding, X11 and the PTY; `command=`
# means whatever the client asks for arrives here in SSH_ORIGINAL_COMMAND instead of
# being run. Until 2026-09-21 the dashboard used lee's personal key, which carries
# passwordless root on this Pi, from a web-facing container. Now a compromise of the
# dashboard can start, stop and restart the camera, toggle HDR and read three numbers.
#
# NOTE: the shebang must stay the first byte of this file (see AGENTS.md).

set -u
SERVICE=picamera.service
DROPIN_DIR="/etc/systemd/system/$SERVICE.d"
DROPIN="$DROPIN_DIR/hdr.conf"

case "${SSH_ORIGINAL_COMMAND:-}" in
  probe)
    # load|mem_pct|temp_c — the format the dashboard parses
    echo "$(awk '{print $1}' /proc/loadavg)|$(free | awk '/Mem:/ {printf "%d", $3/$2*100}')|$(vcgencmd measure_temp 2>/dev/null | grep -oP '[\d.]+' || echo 0)"
    ;;
  start|stop|restart)
    sudo systemctl "$SSH_ORIGINAL_COMMAND" "$SERVICE" || true
    ;;
  hdr-on)
    sudo mkdir -p "$DROPIN_DIR" &&
      printf '[Service]\nEnvironment=HDR=1\n' | sudo tee "$DROPIN" >/dev/null &&
      sudo systemctl daemon-reload && sudo systemctl restart "$SERVICE"
    ;;
  hdr-off)
    sudo rm -f "$DROPIN" && sudo systemctl daemon-reload && sudo systemctl restart "$SERVICE"
    ;;
  *)
    echo "monitor-gate: refused: ${SSH_ORIGINAL_COMMAND:-<interactive login>}" >&2
    logger -t monitor-gate "refused: ${SSH_ORIGINAL_COMMAND:-<interactive login>}"
    exit 1
    ;;
esac
