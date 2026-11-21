"""调用 DeepSeek 的 OpenAI 兼容视觉接口，并流式返回最终答案。"""

import base64
import http.client
import json
import urllib.error
import urllib.request


class DeepSeekError(Exception):
    pass


PROMPT = (
    "识别截图中的题目并直接作答，不复述或解释题目本身，不加开场白、总结等多余文字。"
    "选择题：直接给出选项和简要解释；申论题：直接给出符合要求的完整文章例文；"
    "案例分析题：根据材料和问题直接给出答案；阅读理解：按题目顺序直接回答各问题。"
    "如果有多个问题，请逐题作答。若题目或关键信息不完整或无法看清，请指出，不要编造。"
)


def _sse_events(response):
    """读取 SSE data 字段，支持空行分隔、多行数据和服务端保活。"""
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        yield "\n".join(data)


def stream_image(image: bytes, api_key: str, *, timeout: int = 180):
    encoded = base64.b64encode(image).decode("ascii")
    payload = {
        "model": "deepseek-flash",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{encoded}"
                }},
            ],
        }],
        # 不设置 thinking 和 reasoning_effort，保留 DeepSeek 的默认思考设置。
        "stream": True,
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            saw_text = False
            done = False
            for event in _sse_events(response):
                if event == "[DONE]":
                    done = True
                    break
                result = json.loads(event)
                if not isinstance(result, dict) or result.get("error"):
                    raise DeepSeekError("DeepSeek 流式响应出错，请重试。")
                choices = result.get("choices")
                if not isinstance(choices, list):
                    raise DeepSeekError("DeepSeek 返回了无法解析的数据。")
                if not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
                    raise DeepSeekError("DeepSeek 返回了无法解析的数据。")
                # 忽略思考内容，只转发最终答案。
                text = choice["delta"].get("content")
                if text is not None and not isinstance(text, str):
                    raise DeepSeekError("DeepSeek 返回了无法解析的数据。")
                if text:
                    saw_text = saw_text or bool(text.strip())
                    yield text
                finish_reason = choice.get("finish_reason")
                if finish_reason == "length":
                    raise DeepSeekError("答案达到生成长度限制，可能不完整。")
                if finish_reason in ("insufficient_system_resource", "aborted"):
                    raise DeepSeekError("DeepSeek 提前中断生成，答案可能不完整。")
                if finish_reason == "content_filter":
                    raise DeepSeekError("DeepSeek 内容过滤中断了回答。")
            if not done:
                raise DeepSeekError("DeepSeek 流式响应意外中断，答案可能不完整。")
            if not saw_text:
                raise DeepSeekError("DeepSeek 没有返回文字答案，请重试。")
    except urllib.error.HTTPError as exc:
        hints = {
            400: "请求无效或图片不符合接口要求",
            401: "API Key 无效",
            402: "账户余额不足",
            429: "请求过于频繁",
        }
        hint = hints.get(exc.code, "DeepSeek 服务请求失败")
        exc.close()
        raise DeepSeekError(f"{hint}（HTTP {exc.code}）。") from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise DeepSeekError("无法连接 DeepSeek 或请求超时，请检查网络后重试。") from exc
    except (ValueError, UnicodeError) as exc:
        raise DeepSeekError("DeepSeek 返回了无法解析的数据。") from exc


def solve_image(image: bytes, api_key: str, *, timeout: int = 180) -> str:
    """需要完整文本的调用方可使用此便捷封装。"""
    return "".join(stream_image(image, api_key, timeout=timeout))
