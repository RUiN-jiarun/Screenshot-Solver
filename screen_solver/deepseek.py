"""调用 DeepSeek 的 OpenAI 兼容视觉接口。"""

import base64
import json
import urllib.error
import urllib.request


class DeepSeekError(Exception):
    pass


def solve_image(image: bytes, api_key: str, *, timeout: int = 180) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    payload = {
        "model": "deepseek-flash",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "请识别截图中的题目并解答。给出答案和必要的推理步骤；"
                    "如果题目不完整或无法看清，请说明，不要猜测。"
                )},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{encoded}"
                }},
            ],
        }],
        "stream": False,
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        hints = {
            400: "请求无效或图片不符合接口要求",
            401: "API Key 无效",
            402: "账户余额不足",
            429: "请求过于频繁",
        }
        hint = hints.get(exc.code, "DeepSeek 服务请求失败")
        raise DeepSeekError(f"{hint}（HTTP {exc.code}）。") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeepSeekError("无法连接 DeepSeek 或请求超时，请检查网络后重试。") from exc
    except (ValueError, UnicodeError) as exc:
        raise DeepSeekError("DeepSeek 返回了无法解析的数据。") from exc

    try:
        answer = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek 返回的数据中没有答案。") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise DeepSeekError("DeepSeek 没有返回文字答案，请重试。")
    return answer.strip()
