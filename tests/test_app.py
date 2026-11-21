import base64
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from screen_solver.deepseek import DeepSeekError, solve_image
from screen_solver.server import SolverServer, load_or_create_token


class Response(io.BytesIO):
    pass


class DeepSeekTests(unittest.TestCase):
    def test_request_contains_image_and_extracts_answer(self):
        response = {"choices": [{"message": {"content": " 答案是 42。 "}}]}
        with patch("urllib.request.urlopen", return_value=Response(json.dumps(response).encode())) as call:
            self.assertEqual(solve_image(b"fake png", "test-key"), "答案是 42。")
        request = call.call_args.args[0]
        data = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(data["model"], "deepseek-flash")
        url = data["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), b"fake png")

    def test_http_error_and_empty_response(self):
        error = urllib.error.HTTPError("https://api.deepseek.com", 401, "invalid", {}, None)
        with patch("urllib.request.urlopen", side_effect=error), self.assertRaisesRegex(DeepSeekError, "API Key"):
            solve_image(b"png", "bad-key")
        error.close()
        with patch("urllib.request.urlopen", return_value=Response(b'{"choices":[]}')):
            with self.assertRaisesRegex(DeepSeekError, "没有答案"):
                solve_image(b"png", "test-key")


class TokenTests(unittest.TestCase):
    def test_token_is_reused_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings" / "access-token"
            token = load_or_create_token(path)
            self.assertTrue(token)
            self.assertEqual(load_or_create_token(path), token)
            self.assertEqual(path.read_text().strip(), token)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_empty_token_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "access-token"
            path.write_text("")
            with self.assertRaisesRegex(ValueError, "口令文件为空"):
                load_or_create_token(path)


class ServerTests(unittest.TestCase):
    # 测试本机连接时绕过系统代理。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def setUpClass(cls):
        cls.server = SolverServer(("127.0.0.1", 0), "test-token", demo=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, token, origin=None):
        headers = {"X-Access-Token": token}
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(self.url + "/api/solve", headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_page_and_demo_flow(self):
        with self.opener.open(self.url + "/") as response:
            self.assertIn("截屏并解答", response.read().decode())
        status, data = self.post("test-token", self.url)
        self.assertEqual(status, 200)
        self.assertTrue(data["demo"])
        self.assertIn("没有截屏", data["answer"])

    def test_markdown_assets_are_served(self):
        for name in ("answer.css", "marked.umd.js", "purify.min.js", "render.js"):
            with self.subTest(name=name), self.opener.open(self.url + "/static/" + name) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 0)

    def test_bad_token_and_cross_origin(self):
        self.assertEqual(self.post("wrong")[0], 401)
        self.assertEqual(self.post("test-token", "http://attacker.test")[0], 403)

    def test_busy(self):
        self.server.busy.acquire()
        try:
            self.assertEqual(self.post("test-token")[0], 409)
        finally:
            self.server.busy.release()

    def test_real_flow_uses_capture_then_model(self):
        self.server.demo = False
        self.server.api_key = "test-key"
        try:
            with patch("screen_solver.server.capture_screen", return_value=b"screenshot") as capture, \
                 patch("screen_solver.server.solve_image", return_value="模型答案") as solve:
                status, data = self.post("test-token")
                self.assertEqual(status, 200)
                self.assertEqual(data["answer"], "模型答案")
                self.assertFalse(data["demo"])
                capture.assert_called_once_with()
                solve.assert_called_once_with(b"screenshot", "test-key")
        finally:
            self.server.demo = True
            self.server.api_key = ""

    def test_error_is_reported_and_lock_released(self):
        with patch.object(self.server, "solve", side_effect=DeepSeekError("模拟故障")):
            self.assertEqual(self.post("test-token"), (502, {"error": "模拟故障"}))
        self.assertEqual(self.post("test-token")[0], 200)


if __name__ == "__main__":
    unittest.main()
