"""生成独立 HTML 答案页。"""

import json
import os
from pathlib import Path
import tempfile
import webbrowser

STATIC = Path(__file__).with_name("static")


def result_html(answer):
    # JSON 中的 < 必须转义，避免答案提前结束 script 标签。
    data = json.dumps(answer, ensure_ascii=False).replace("<", "\\u003c")
    styles = (STATIC / "answer.css").read_text(encoding="utf-8")
    scripts = [(STATIC / name).read_text(encoding="utf-8")
               for name in ("marked.umd.js", "purify.min.js", "render.js")]
    # 防止将来升级依赖时，脚本内出现 HTML 的结束标签。
    if any("</script" in script.lower() for script in scripts):
        raise ValueError("Markdown 资源包含不安全的脚本结束标签。")
    script_tags = "\n".join(f"<script>{script}</script>" for script in scripts)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>截图解答结果</title>
<style>
body {{ max-width: 760px; margin: 40px auto; padding: 0 20px; font: 16px/1.6 system-ui, sans-serif; color: #222; }}
{styles}
</style></head><body>
<h1>截图解答结果</h1>
<div id="answer" class="markdown-answer"></div>
<script type="application/json" id="answer-data">{data}</script>
{script_tags}
<script>
const text = JSON.parse(document.getElementById('answer-data').textContent);
renderMarkdown(document.getElementById('answer'), text);
</script>
</body></html>'''


def show_result(answer, path=None):
    """写入私有 HTML 文件并尝试打开；返回文件路径与打开状态。"""
    content = result_html(answer)
    if path is None:
        fd, name = tempfile.mkstemp(prefix="screen-solver-result-", suffix=".html")
        path = Path(name)
    else:
        path = Path(path).expanduser().resolve()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(content)
    try:
        opened = webbrowser.open(path.as_uri())
    except (webbrowser.Error, OSError):
        opened = False
    return path, opened
