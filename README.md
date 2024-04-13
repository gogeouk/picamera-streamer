# Installing Picamera instructions
- Latest versions of Raspberry Pi OS include camera support.
- 1. Physically install camera onto Pi.
- 2. Download latest version of Raspberry Pi imager.
- 3. Create SD card using imager by choosing appropriate Pi version, "Raspberry Pi OS" version and flash drive (use Edit Settings to also set up login, ssh access, wifi etc.).
- 4. Put into Pi and start up. If necessary (and didn't do it during imaging) set up login, ssh access, network and anything else necessary for your system.
- 5. Login, make a directory in home folder (picamera) and copy in picamera.py file.
- 6. **TEST** python picamera.py
- 7. **TEST** go to 192.168.1.80:8000 on browser for live video.
- 8. **TEST** hit 192.168.1.80:8000/current.jpg for snapshot.
- 9. Edit **picamera.service** with correct username and script paths
- 10. Copy **picamera.service** to systemd directory (`sudo cp picamera.service /etc/systemd/system`)
- 11. Save and reload systemd (`sudo systemctl daemon-reload`)
- 12. Enable and restart the service:
- ```
  sudo systemctl enable picamera.service
  sudo systemctl start picamera.service
  ```