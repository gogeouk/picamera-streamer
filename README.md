
## Introduction
Picamera Streamer is a modified version of one of the [Raspbery Pi picamera2](https://github.com/raspberrypi/picamera2) sample files: it provides an HTTP live stream (MJPEG) of the camera as well as an added snapshotting endpoint.
These two endpoints are used by the (weather) webcam feature in GoGeo's upcoming weather monitoring server.

## Installation
These instructions will get the server up and running. They will add the script as a service to `systemd` so that it runs on startup and is restarted on failure.
Note that to use this will the GoGo weather server you will need to set up your Pi to serve https sites or the camera will not load on modern browsers.
Latest versions of Raspberry Pi OS include camera support.
1. Physically install camera onto Pi.
2. Download latest version of Raspberry Pi imager.
3. Create SD card using imager by choosing appropriate Pi version, "Raspberry Pi     OS" version and flash drive (use Edit Settings to also set up login, ssh access, wifi etc.).
4. Put into Pi and start up. If necessary (and didn't do it during imaging) set up login, ssh access, network and anything else necessary for your system.
5. Login, make a directory in home folder (picamera) and copy in picamera.py file.
6. **TEST** python picamera.py
7. **TEST** go to http://<server address>:8000 on browser for live video.
8. **TEST** hit http://<server address>:8000/current.jpg for snapshot.
9. Edit **picamera.service** with correct username and script paths
10. Copy **picamera.service** to systemd directory (`sudo cp picamera.service /etc/systemd/system`)
11. Save and reload systemd (`sudo systemctl daemon-reload`)
12. Enable and restart the service:

        sudo systemctl enable picamera.service
        sudo systemctl start picamera.service