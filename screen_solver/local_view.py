"""本机调试用的临时、仅回环地址可访问的实时结果页。"""

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .results import result_html


class LiveResult:
    def __init__(self):
        self.path = "/" + secrets.token_urlsafe(24)
        self.text = ""
        self.status = "running"
        self.error = ""
        self.lock = threading.Lock()
        self.seen = threading.Event()
        view = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                if self.path == view.path:
                    body = view._page().encode("utf-8")
                    content_type = "text/html; charset=utf-8"
                    terminal = False
                elif self.path == view.path + "/state":
                    with view.lock:
                        state = {"text": view.text, "status": view.status, "error": view.error}
                    body = json.dumps(state, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                    terminal = state["status"] != "running"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                try:
                    self.wfile.write(body)
                    self.wfile.flush()
                    if terminal:
                        view.seen.set()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.1}, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}{self.path}"

    def _page(self):
        state_url = json.dumps(self.path + "/state")
        live_script = '''
<p id="live-status" role="status">正在思考，答案生成后会实时显示……</p>
<script>
async function update() {
  const status = document.getElementById('live-status');
  try {
    const response = await fetch(STATE_URL, {cache: 'no-store'});
    if (!response.ok) throw new Error('无法读取结果');
    const result = await response.json();
    renderMarkdown(document.getElementById('answer'), result.text);
    if (result.status === 'done') {
      status.textContent = '解答完成。';
    } else if (result.status === 'error') {
      status.textContent = '出错：' + result.error;
    } else {
      status.textContent = result.text ? '正在生成答案……' : '正在思考，答案生成后会实时显示……';
      setTimeout(update, 200);
    }
  } catch (error) {
    status.textContent = '连接中断：' + error.message;
  }
}
update();
</script>
'''.replace("STATE_URL", state_url)
        page = result_html("")
        closing = "</body></html>"
        if not page.endswith(closing):
            raise ValueError("结果页模板不完整。")
        return page[:-len(closing)] + live_script + closing

    def __enter__(self):
        self.thread.start()
        return self

    def open(self):
        try:
            return webbrowser.open(self.url)
        except (webbrowser.Error, OSError):
            return False

    def append(self, text):
        with self.lock:
            self.text += text

    def finish(self, error=""):
        with self.lock:
            self.status = "error" if error else "done"
            self.error = error

    def wait_for_viewer(self, timeout=5):
        return self.seen.wait(timeout)

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
