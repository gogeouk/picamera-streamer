
#!/bin/bash
if ! curl -sf http://localhost:8000/; then
  echo "$(date): Health check failed, restarting service..." >> /home/lee/picamera_health.log
  systemctl restart picamera.service
fi
