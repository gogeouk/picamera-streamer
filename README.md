# Installing Picamera instructions
- Latest versions of Raspberry Pi OS include camera support.
- Physically install camera onto Pi.
  logseq.order-list-type:: number
- Download latest version of Raspberry Pi imager.
  logseq.order-list-type:: number
- Create SD card using imager by choosing appropriate Pi version, "Raspberry Pi OS" version and flash drive (use Edit Settings to also set up login, ssh access, wifi etc.).
  logseq.order-list-type:: number
- Put into Pi and start up. If necessary (and didn't do it during imaging) set up login, ssh access, network and anything else necessary for your system.
  logseq.order-list-type:: number
- Login, make a directory in home folder (picamera) and copy in picamera.py file.
  logseq.order-list-type:: number
- **TEST** python picamera.py
  logseq.order-list-type:: number
- **TEST** go to 192.168.1.80:8000 on browser for live video.
  logseq.order-list-type:: number
- **TEST** hit 192.168.1.80:8000/current.jpg for snapshot.
  logseq.order-list-type:: number
- Edit **picamera.service** with correct username and script paths
  logseq.order-list-type:: number
- Copy **picamera.service** to systemd directory (`sudo cp picamera.service /etc/systemd/system`)
  logseq.order-list-type:: number
- Save and reload systemd (`sudo systemctl daemon-reload`)
  logseq.order-list-type:: number
- Enable and restart the service:
  logseq.order-list-type:: number
- ```
  sudo systemctl enable picamera.service
  sudo systemctl start picamera.service
  ```
	-
-