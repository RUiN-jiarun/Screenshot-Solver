"""HTTP 服务：辅助设备通过浏览器触发截屏并读取答案。"""

import argparse
import getpass
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .capture import CaptureError, capture_screen
from .deepseek import DeepSeekError, stream_image

PAGE = Path(__file__).with_name("web.html").read_bytes()
STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/static/answer.css": "text/css; charset=utf-8",
    "/static/marked.umd.js": "text/javascript; charset=utf-8",
    "/static/purify.min.js": "text/javascript; charset=utf-8",
    "/static/render.js": "text/javascript; charset=utf-8",
}


class SolverServer(ThreadingHTTPServer):
    def __init__(self, address, token, api_key="", demo=False):
        super().__init__(address, SolverHandler)
        self.token = token
        self.api_key = api_key
        self.demo = demo
        self.busy = threading.Lock()

    def solve(self):
        if self.demo:
            yield "【演示模式】连接成功！这是模拟答案，没有截屏，也没有调用 DeepSeek。"
        else:
            yield from stream_image(capture_screen(), self.api_key)


class SolverHandler(BaseHTTPRequestHandler):
    # 日志不输出请求内容或密钥。
    def log_message(self, format, *args):
        pass

    def send_content(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data):
        self.send_content(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8")

    def do_GET(self):
        if self.path == "/":
            self.send_content(200, PAGE, "text/html; charset=utf-8")
        elif self.path in ASSETS:
            content = (STATIC / self.path.rsplit("/", 1)[-1]).read_bytes()
            self.send_content(200, content, ASSETS[self.path])
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/api/solve", "/api/solve-stream"):
            self.send_error(404)
            return
        # 非浏览器客户端不一定有 Origin；浏览器跨站请求必须拒绝。
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme != "http" or parsed.netloc != self.headers.get("Host")
                    or parsed.path or parsed.query or parsed.fragment):
                self.send_json(403, {"error": "拒绝跨站请求。"})
                return
        supplied = self.headers.get("X-Access-Token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), self.server.token.encode("utf-8")):
            self.send_json(401, {"error": "访问口令错误。"})
            return
        if not self.server.busy.acquire(blocking=False):
            self.send_json(409, {"error": "正在处理上一条请求，请稍后再试。"})
            return
        # 旧版网页会将 /api/solve 的响应整体解析为 JSON，保留该接口。
        if self.path == "/api/solve":
            try:
                try:
                    answer = "".join(self.server.solve())
                except (CaptureError, DeepSeekError) as exc:
                    self.send_json(502, {"error": str(exc)})
                except Exception:
                    self.send_json(500, {"error": "服务发生意外错误，请检查服务端状态。"})
                else:
                    self.send_json(200, {"answer": answer, "demo": self.server.demo})
            finally:
                self.server.busy.release()
            return

        # HTTP/1.0 以连接关闭表示流结束，逐条刷新 NDJSON 给浏览器。
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            def emit(event):
                line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
                self.wfile.write(line)
                self.wfile.flush()

            emit({"type": "start", "demo": self.server.demo})
            try:
                for chunk in self.server.solve():
                    emit({"type": "delta", "text": chunk})
                emit({"type": "done"})
            except (CaptureError, DeepSeekError) as exc:
                emit({"type": "error", "error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                emit({"type": "error", "error": "服务发生意外错误，请检查服务端状态。"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.busy.release()


def load_or_create_token(path):
    """保存访问口令，保证服务重启后无需重新配对。"""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(f"访问口令文件为空：{path}，请删除该文件后重试。")
        return token
    token = secrets.token_urlsafe(24)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(token + "\n")
    return token


def main():
    parser = argparse.ArgumentParser(description="局域网截图解答服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址；局域网使用 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")
    parser.add_argument("--demo", action="store_true", help="演示模式：不截图、不调用模型")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not args.demo and not api_key:
        try:
            api_key = getpass.getpass("DeepSeek API Key（输入不显示）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return
        if not api_key:
            parser.error("API Key 不能为空。")

    try:
        token = (os.environ.get("SCREEN_SOLVER_TOKEN", "").strip()
                 or load_or_create_token(Path.home() / ".screen-solver" / "access-token"))
        server = SolverServer((args.host, args.port), token, api_key, args.demo)
    except (OSError, ValueError) as exc:
        parser.error(f"无法启动服务：{exc}")
    print(f"服务已启动：监听 {args.host}:{server.server_port}")
    print(f"访问口令：{token}")
    print("请仅在可信局域网使用。按 Ctrl+C 停止服务。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()
