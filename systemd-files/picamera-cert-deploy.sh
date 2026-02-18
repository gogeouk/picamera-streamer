#!/bin/bash
# Certbot deploy hook for picamera-streamer
#
# Install to: /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
# Make executable: sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/picamera-cert-deploy.sh
#
# This script runs automatically after every successful certbot certificate renewal.
# It copies the new certificates into the picamera-streamer certificates directory
# and restarts the service.
#
# Edit DOMAIN and DEST_DIR to match your setup before installing.

DOMAIN="your-domain.duckdns.org"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
DEST_DIR="/home/pi/picamera-streamer/certificates"
SERVICE="picamera.service"
LOG="/var/log/picamera-cert-deploy.log"

cp "$CERT_DIR/fullchain.pem" "$DEST_DIR/fullchain.pem"
cp "$CERT_DIR/privkey.pem"   "$DEST_DIR/privkey.pem"
chmod 644 "$DEST_DIR/fullchain.pem"
chmod 600 "$DEST_DIR/privkey.pem"
chown pi:pi "$DEST_DIR/fullchain.pem" "$DEST_DIR/privkey.pem"

systemctl restart "$SERVICE"
echo "$(date): Certs deployed and $SERVICE restarted" >> "$LOG"
