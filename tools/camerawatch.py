"""
Notice a camera that has stopped delivering, and get out of the way so systemd
restarts the streamer at once.

Why (20 Oct 2026): three times in three days the camera on one Pi stopped returning
pictures with no error at all, in the streamer or in the kernel. The capture call
simply never came back; /status went on answering for under a minute, then the
whole process went quiet. health_check.sh only looks every five minutes, so each
stall cost two to five of the archive's minute-by-minute frames.

So every camera call the streamer waits on has a time limit, and a background probe
asks the camera for a frame's metadata every few seconds, which also catches a stall
while nobody is asking for a picture. Either way, a camera that does not answer in
time ends the process with a non-zero code (Restart=on-failure brings it straight
back). os._exit, not sys.exit: a stalled camera can hang a clean shutdown too.

The probe also records the camera sensor's own temperature when the sensor reports
it, for tools/thermal-log.sh: whether these stalls follow the heat is an open question.
"""

import concurrent.futures
import logging
import os
import threading
import time

# Exit code for "the camera stalled"; anything non-zero makes systemd restart us.
STALL_EXIT_CODE = 3


def exit_for_restart(what, seconds):
    logging.error("Camera stalled: %s got no answer in %.0f s; exiting so systemd restarts the streamer", what, seconds)
    logging.shutdown()
    os._exit(STALL_EXIT_CODE)


class CameraWatch:
    def __init__(self, picam2, timeout=10.0, interval=15.0, sensor_temp_file=None, on_stall=exit_for_restart):
        self.picam2 = picam2
        self.timeout = timeout
        self.interval = interval
        self.sensor_temp_file = sensor_temp_file
        self.on_stall = on_stall
        self.last_answer = time.monotonic()

    def timed(self, what, start):
        """Run a camera call started with wait=False, waiting at most `timeout` for it."""
        job = start()
        try:
            result = self.picam2.wait(job, timeout=self.timeout)
        except (TimeoutError, concurrent.futures.TimeoutError):
            self.on_stall(what, self.timeout)
            return None
        self.last_answer = time.monotonic()
        return result

    def probe(self):
        metadata = self.timed("a metadata probe", lambda: self.picam2.capture_metadata(wait=False))
        if metadata and self.sensor_temp_file and "SensorTemperature" in metadata:
            self._write_sensor_temp(metadata["SensorTemperature"])
        return metadata

    def _write_sensor_temp(self, celsius):
        try:
            tmp = f"{self.sensor_temp_file}.tmp"
            with open(tmp, "w") as f:
                f.write(f"{celsius:.1f}\n")
            os.replace(tmp, self.sensor_temp_file)
        except OSError as e:
            logging.warning("Could not record the sensor temperature: %s", e)

    def run_forever(self):
        while True:
            time.sleep(self.interval)
            try:
                self.probe()
            except Exception as e:  # the probe must never be what stops the stream
                logging.warning("Camera probe failed: %s", e)

    def start(self):
        threading.Thread(target=self.run_forever, name="camera-watch", daemon=True).start()
        return self
