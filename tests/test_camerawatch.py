"""Run with: python3 -m unittest discover -s tests   (from the repo root; no camera needed)"""
import concurrent.futures
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.camerawatch import CameraWatch  # noqa: E402


class FakeCamera:
    """Jobs are futures; a stalled camera never completes them."""

    def __init__(self, metadata=None, stalled=False):
        self.metadata = metadata if metadata is not None else {"ExposureTime": 1000}
        self.stalled = stalled
        self.waits = []

    def _job(self, value):
        f = concurrent.futures.Future()
        if not self.stalled:
            f.set_result(value)
        return f

    def capture_metadata(self, wait=None):
        assert wait is False, "the watch must start calls without waiting"
        return self._job(self.metadata)

    def capture_file(self, data, format=None, wait=None):
        assert wait is False
        if not self.stalled:
            data.write(b"\xff\xd8jpeg\xff\xd9")
        return self._job({})

    def wait(self, job, timeout=None):
        self.waits.append(timeout)
        return job.result(timeout=timeout)


class CameraWatchTest(unittest.TestCase):
    def setUp(self):
        self.stalls = []
        self.on_stall = lambda what, seconds: self.stalls.append((what, seconds))

    def test_a_working_camera_answers_and_is_not_restarted(self):
        cam = FakeCamera(metadata={"SensorTemperature": 41.25})
        watch = CameraWatch(cam, timeout=0.05, on_stall=self.on_stall)
        self.assertEqual(watch.probe(), {"SensorTemperature": 41.25})
        self.assertEqual(self.stalls, [])
        self.assertEqual(cam.waits, [0.05], "every wait has the time limit")

    def test_a_stalled_probe_asks_for_a_restart(self):
        watch = CameraWatch(FakeCamera(stalled=True), timeout=0.05, on_stall=self.on_stall)
        self.assertIsNone(watch.probe())
        self.assertEqual(self.stalls, [("a metadata probe", 0.05)])

    def test_a_stalled_picture_asks_for_a_restart(self):
        import io
        cam = FakeCamera(stalled=True)
        watch = CameraWatch(cam, timeout=0.05, on_stall=self.on_stall)
        data = io.BytesIO()
        watch.timed("/current.jpg", lambda: cam.capture_file(data, format="jpeg", wait=False))
        self.assertEqual(self.stalls, [("/current.jpg", 0.05)])

    def test_a_picture_is_written_when_the_camera_answers(self):
        import io
        cam = FakeCamera()
        watch = CameraWatch(cam, timeout=0.05, on_stall=self.on_stall)
        data = io.BytesIO()
        watch.timed("/current.jpg", lambda: cam.capture_file(data, format="jpeg", wait=False))
        self.assertTrue(data.getvalue().startswith(b"\xff\xd8"))
        self.assertEqual(self.stalls, [])

    def test_the_sensor_temperature_is_recorded_when_reported(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sensor-temp")
            CameraWatch(FakeCamera(metadata={"SensorTemperature": 47.0}), timeout=0.05,
                        sensor_temp_file=path, on_stall=self.on_stall).probe()
            with open(path) as f:
                self.assertEqual(f.read(), "47.0\n")
            # A sensor that does not report it leaves the file alone.
            CameraWatch(FakeCamera(metadata={}), timeout=0.05, sensor_temp_file=path, on_stall=self.on_stall).probe()
            with open(path) as f:
                self.assertEqual(f.read(), "47.0\n")


if __name__ == "__main__":
    unittest.main()
