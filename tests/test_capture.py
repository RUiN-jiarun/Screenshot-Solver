import struct
import subprocess
import unittest
from unittest.mock import patch

from screen_solver.capture import CaptureError, capture_screen


class CaptureTests(unittest.TestCase):
    def fake_capture(self, command, **kwargs):
        png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1920, 1080)
        with open(command[-1], "wb") as image:
            image.write(png)

    @patch("screen_solver.capture.sys.platform", "darwin")
    def test_mac_capture(self):
        with patch("screen_solver.capture.subprocess.run", side_effect=self.fake_capture) as run:
            image = capture_screen()
        self.assertTrue(image.startswith(b"\x89PNG"))
        self.assertEqual(run.call_args.args[0][:4], ["screencapture", "-x", "-m", "-t"])

    @patch("screen_solver.capture.sys.platform", "darwin")
    def test_permission_or_command_failure(self):
        with patch("screen_solver.capture.subprocess.run", side_effect=subprocess.CalledProcessError(1, "screencapture")):
            with self.assertRaisesRegex(CaptureError, "屏幕录制权限"):
                capture_screen()

    @patch("screen_solver.capture.sys.platform", "darwin")
    def test_image_limit(self):
        def oversized(command, **kwargs):
            with open(command[-1], "wb") as image:
                image.write(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 8193, 100))
        with patch("screen_solver.capture.subprocess.run", side_effect=oversized):
            with self.assertRaisesRegex(CaptureError, "大小限制"):
                capture_screen()


if __name__ == "__main__":
    unittest.main()
