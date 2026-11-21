import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import debug_local
from screen_solver.capture import CaptureError
from screen_solver.deepseek import DeepSeekError


class LocalDebugTests(unittest.TestCase):
    def test_full_flow(self):
        output = io.StringIO()
        viewer = MagicMock()
        viewer.url = 'http://127.0.0.1:1/test'
        viewer.open.return_value = True
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), \
             patch("debug_local.time.sleep") as sleep, \
             patch("debug_local.capture_screen", return_value=b"screenshot") as capture, \
             patch("debug_local.stream_image", return_value=iter(["模型", "答案"])) as solve, \
             patch("debug_local.LiveResult") as live, \
             patch("debug_local.write_result", return_value=Path("/tmp/result.html")) as save, \
             contextlib.redirect_stdout(output):
            live.return_value.__enter__.return_value = viewer
            self.assertEqual(debug_local.main([]), 0)
        sleep.assert_called_once_with(5)
        capture.assert_called_once_with()
        solve.assert_called_once_with(b"screenshot", "test-key")
        self.assertEqual(viewer.append.call_count, 2)
        viewer.finish.assert_called_once_with()
        viewer.wait_for_viewer.assert_called_once_with()
        save.assert_called_once_with("模型答案", None)
        self.assertIn("模型答案", output.getvalue())
        self.assertIn("/tmp/result.html", output.getvalue())

    def test_capture_only_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            with patch.dict(os.environ, {}, clear=True), \
                 patch("debug_local.time.sleep"), \
                 patch("debug_local.capture_screen", return_value=b"screenshot"), \
                 patch("debug_local.getpass.getpass") as getpass, \
                 patch("debug_local.stream_image") as solve, \
                 patch("debug_local.LiveResult") as live, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(debug_local.main(["--delay", "0", "--capture-only", "--save", str(path)]), 0)
            getpass.assert_not_called()
            solve.assert_not_called()
            live.assert_not_called()
            self.assertEqual(path.read_bytes(), b"screenshot")
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            path.write_bytes(b"original")
            with patch("debug_local.time.sleep"), \
                 patch("debug_local.capture_screen", return_value=b"screenshot"), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(debug_local.main(["--capture-only", "--save", str(path)]), 1)
            self.assertEqual(path.read_bytes(), b"original")

    def test_capture_error_and_model_error(self):
        for capture_effect, model_effect in [(CaptureError("截屏失败"), None), (b"image", DeepSeekError("模型失败"))]:
            capture = {"side_effect": capture_effect} if isinstance(capture_effect, Exception) else {"return_value": capture_effect}
            with self.subTest(capture_effect=capture_effect), \
                 patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), \
                 patch("debug_local.time.sleep"), \
                 patch("debug_local.capture_screen", **capture), \
                 patch("debug_local.stream_image", side_effect=model_effect), \
                 patch("debug_local.LiveResult"), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(debug_local.main([]), 1)

    def test_invalid_delay(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            debug_local.main(["--delay", "-1"])
        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
