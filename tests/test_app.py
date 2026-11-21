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

from screen_solver.deepseek import DeepSeekError, stream_image
from screen_solver.server import SolverServer, load_or_create_token


class Response(io.BytesIO):
    pass


def sse_chunk(data):
    return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8")


class DeepSeekTests(unittest.TestCase):
    def test_request_streams_only_final_answer(self):
        events = (b": keepalive\n\n"
                  + sse_chunk({"choices": [{"delta": {"reasoning_content": "隐藏思考"}}]})
                  + sse_chunk({"choices": [{"delta": {"content": " 答案"}}]})
                  + sse_chunk({"choices": [{"delta": {"content": "是 42。 "}, "finish_reason": "stop"}]})
                  + b"data: [DONE]\n\n")
        with patch("urllib.request.urlopen", return_value=Response(events)) as call:
            self.assertEqual(list(stream_image(b"fake png", "test-key")), [" 答案", "是 42。 "])
        request = call.call_args.args[0]
        data = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(data["model"], "deepseek-flash")
        self.assertTrue(data["stream"])
        self.assertNotIn("thinking", data)
        self.assertNotIn("reasoning_effort", data)
        prompt = data["messages"][0]["content"][0]["text"]
        for kind in ("选择题", "申论题", "案例分析题", "阅读理解"):
            self.assertIn(kind, prompt)
        url = data["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), b"fake png")

    def test_http_error_and_empty_response(self):
        error = urllib.error.HTTPError("https://api.deepseek.com", 401, "invalid", {}, None)
        with patch("urllib.request.urlopen", side_effect=error), self.assertRaisesRegex(DeepSeekError, "API Key"):
            list(stream_image(b"png", "bad-key"))
        with patch("urllib.request.urlopen", return_value=Response(b'data: [DONE]\n\n')):
            with self.assertRaisesRegex(DeepSeekError, "没有返回文字"):
                list(stream_image(b"png", "test-key"))

    def test_partial_stream_is_not_silently_successful(self):
        cases = [
            (sse_chunk({"choices": [{"delta": {"content": "部分"}}]}), "中断"),
            (sse_chunk({"choices": [{"delta": {"content": "部分"}, "finish_reason": "length"}]}) + b'data: [DONE]\n\n', "长度限制"),
            (sse_chunk({"choices": [{"delta": {"content": "部分"}, "finish_reason": "aborted"}]}) + b'data: [DONE]\n\n', "中断"),
            (sse_chunk({"choices": [{"delta": {}, "finish_reason": "content_filter"}]}) + b'data: [DONE]\n\n', "内容过滤"),
            (b'data: invalid json\n\n', "无法解析"),
        ]
        for response, message in cases:
            with self.subTest(message=message), patch("urllib.request.urlopen", return_value=Response(response)):
                with self.assertRaisesRegex(DeepSeekError, message):
                    list(stream_image(b"png", "test-key"))

    def test_multiline_sse_data(self):
        events = (b'data: {"choices":\n' + b'data: [{"delta":{"content":"ok"}}]}\n\n'
                  + b'data: [DONE]\n\n')
        with patch("urllib.request.urlopen", return_value=Response(events)):
            self.assertEqual(list(stream_image(b"png", "test-key")), ["ok"])


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

    def post(self, token, origin=None, path="/api/solve-stream"):
        headers = {"X-Access-Token": token}
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(self.url + path, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=5) as response:
                if response.headers.get_content_type() == "application/x-ndjson":
                    return response.status, [json.loads(line) for line in response if line.strip()]
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.load(exc)

    def test_page_and_demo_flow(self):
        with self.opener.open(self.url + "/") as response:
            self.assertIn("截屏并解答", response.read().decode())
        status, events = self.post("test-token", self.url)
        self.assertEqual(status, 200)
        self.assertTrue(events[0]["demo"])
        self.assertIn("没有截屏", events[1]["text"])
        self.assertEqual(events[-1]["type"], "done")

    def test_legacy_page_still_receives_one_json_object(self):
        status, result = self.post("test-token", path="/api/solve")
        self.assertEqual(status, 200)
        self.assertTrue(result["demo"])
        self.assertIn("没有截屏", result["answer"])

    def test_legacy_errors_still_return_json(self):
        def failing():
            yield "部分答案"
            raise DeepSeekError("模拟故障")
        with patch.object(self.server, "solve", side_effect=failing):
            self.assertEqual(self.post("test-token", path="/api/solve"), (502, {"error": "模拟故障"}))
        self.assertEqual(self.post("test-token")[0], 200)

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
                 patch("screen_solver.server.stream_image", return_value=iter(["模型", "答案"])) as solve:
                status, events = self.post("test-token")
                self.assertEqual(status, 200)
                self.assertFalse(events[0]["demo"])
                self.assertEqual([e["text"] for e in events if e["type"] == "delta"], ["模型", "答案"])
                self.assertEqual(events[-1]["type"], "done")
                capture.assert_called_once_with()
                solve.assert_called_once_with(b"screenshot", "test-key")
        finally:
            self.server.demo = True
            self.server.api_key = ""

    def test_error_is_reported_and_lock_released(self):
        def failing():
            yield "部分答案"
            raise DeepSeekError("模拟故障")
        with patch.object(self.server, "solve", side_effect=failing):
            status, events = self.post("test-token")
            self.assertEqual(status, 200)
            self.assertEqual(events[-1], {"type": "error", "error": "模拟故障"})
            self.assertEqual(events[1]["text"], "部分答案")
        self.assertEqual(self.post("test-token")[0], 200)

    def test_first_chunk_arrives_before_completion(self):
        release = threading.Event()
        def slow_answer():
            yield "第一段"
            if not release.wait(5):
                raise DeepSeekError("测试超时")
            yield "第二段"
        request = urllib.request.Request(self.url + "/api/solve-stream", headers={"X-Access-Token": "test-token"}, method="POST")
        try:
            with patch.object(self.server, "solve", side_effect=slow_answer):
                with self.opener.open(request, timeout=5) as response:
                    self.assertEqual(json.loads(response.readline())["type"], "start")
                    self.assertEqual(json.loads(response.readline())["text"], "第一段")
                    self.assertEqual(self.post("test-token")[0], 409)
                    release.set()
                    self.assertEqual(json.loads(response.readline())["text"], "第二段")
                    self.assertEqual(json.loads(response.readline())["type"], "done")
        finally:
            release.set()



if __name__ == "__main__":
    unittest.main()
