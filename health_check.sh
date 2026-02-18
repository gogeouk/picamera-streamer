
#!/bin/bash
if ! curl -sf --max-time 10 http://localhost:8000/current.jpg -o /dev/null; then
  echo "$(date): Health check failed, restarting service..." >> /home/lee/picamera_health.log
  systemctl restart picamera.service
fi
