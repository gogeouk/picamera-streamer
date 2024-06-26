
## Introduction
Picamera Streamer is a modified version of one of the [Raspbery Pi picamera2](https://github.com/raspberrypi/picamera2) sample files: it provides an HTTP live stream (MJPEG) of the camera as well as an added snapshotting endpoint.
These two endpoints are used by the (weather) webcam feature in GoGeo's upcoming weather monitoring server.

## Installation
These instructions will get the server up and running. They will add the script as a service to `systemd` so that it runs on startup and is restarted on failure.

Note that to use this with the GoGo weather server you will need to set up your Pi to serve https sites or the camera will not load on modern browsers.

Latest versions of Raspberry Pi OS include camera support.

1. Physically install camera onto Pi.
2. Download latest version of Raspberry Pi imager.
3. Create SD card using imager by choosing appropriate Pi version, "Raspberry Pi     OS" version and flash drive (use Edit Settings to also set up login, ssh access, wifi etc.).
4. Put into Pi and start up. If necessary (and didn't do it during imaging) set up login, ssh access, network and anything else necessary for your system.
5. Login, make a directory in home folder (picamera) and copy in picamera.py file.
6. If necessary, install the picamera2 library (`pip3 install picamera2`)
7. **TEST** python3 picamera.py
8. **TEST** go to `http://server-address:8000` on browser for live video.
9. **TEST** hit `http://server-address:8000/current.jpg` for snapshot.
10. Edit **picamera.service** with correct username and script paths
11. Copy **picamera.service** to systemd directory (`sudo cp picamera.service /etc/systemd/system`)
12. Save and reload systemd (`sudo systemctl daemon-reload`)
13. Enable and restart the service:

        sudo systemctl enable picamera.service
        sudo systemctl start picamera.service
        
## Configuration
 
Create a .env file to configure the service; a `sample.env` file contains the most used settings. Keys here include `NAME` to give your camera a name (this shows on the default output), `PORT` to set the server port, and `RESOLUTION` to override the default resolution (the setting **must* be given in the format of WIDTHxHEIGHT (eg. `1280x720`).

## Self managing HTTPS certificates

If you wish to quickly get an HTTPS version of the server up and are willing to self manage SSL certificates, you can use the configuration keys of `KEYFILE` and `CERTFILE` to point to the private key and full chain certificates of your SSL certificate. This is quick and dirty (you can use the Letsencrypt `certbot` to generate these keys) but means you’ll need to manually update on expiry, so is not really recommended.
