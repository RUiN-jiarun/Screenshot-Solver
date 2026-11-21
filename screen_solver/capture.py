"""截取主屏幕，返回 PNG 字节。"""

import os
import struct
import subprocess
import sys
import tempfile


class CaptureError(Exception):
    pass


def capture_screen() -> bytes:
    if sys.platform == "darwin":
        # 系统命令无需额外依赖；-x 静音，-m 仅主屏幕。
        try:
            with tempfile.TemporaryDirectory(prefix="screen-solver-") as directory:
                path = os.path.join(directory, "screen.png")
                subprocess.run(
                    ["screencapture", "-x", "-m", "-t", "png", path],
                    check=True, capture_output=True, timeout=15,
                )
                with open(path, "rb") as image:
                    data = image.read()
        except (OSError, subprocess.SubprocessError) as exc:
            raise CaptureError(
                "截屏失败，请检查 macOS 的屏幕录制权限，并确保电脑已解锁。"
            ) from exc
    else:
        try:
            import mss
            import mss.tools
        except ImportError as exc:
            raise CaptureError("请先安装截屏依赖：python -m pip install mss") from exc
        try:
            with mss.mss() as screen:
                image = screen.grab(screen.monitors[1])
                data = mss.tools.to_png(image.rgb, image.size)
        except Exception as exc:
            raise CaptureError("截屏失败，请检查屏幕捕获权限和图形桌面环境。") from exc

    # DeepSeek 的单张图片限制为 32 MiB、每边不超过 8192 像素。
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 24:
        raise CaptureError("截屏结果无效，请检查屏幕录制权限。")
    width, height = struct.unpack(">II", data[16:24])
    if len(data) > 32 * 1024 * 1024 or max(width, height) > 8192:
        raise CaptureError("截图超过 DeepSeek 的图片大小限制，请降低屏幕分辨率后重试。")
    return data
