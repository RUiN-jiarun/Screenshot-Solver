"""不依赖辅助设备，直接测试截图和 DeepSeek 解答。"""

import argparse
import getpass
import os
from pathlib import Path
import sys
import time

from screen_solver.capture import CaptureError, capture_screen
from screen_solver.deepseek import DeepSeekError, stream_image
from screen_solver.local_view import LiveResult
from screen_solver.results import write_result


def non_negative_seconds(value):
    try:
        seconds = int(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("等待时间必须是非负整数。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="本机测试截屏与 DeepSeek 解答")
    parser.add_argument("--delay", type=non_negative_seconds, default=5,
                        help="截屏前等待秒数（默认 5 秒）")
    parser.add_argument("--capture-only", action="store_true", help="只截屏，不调用 DeepSeek")
    parser.add_argument("--save", type=Path, metavar="文件.png", help="额外保存截图（不覆盖已有文件）")
    parser.add_argument("--html", type=Path, metavar="文件.html", help="指定结果 HTML 文件（不覆盖已有文件）")
    args = parser.parse_args(argv)

    try:
        api_key = ""
        if not args.capture_only:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
            if not api_key:
                api_key = getpass.getpass("DeepSeek API Key（输入不显示）: ").strip()
            if not api_key:
                print("API Key 不能为空。", file=sys.stderr)
                return 1

        print(f"将在 {args.delay} 秒后截取主屏幕，请切换到题目页面。", flush=True)
        time.sleep(args.delay)
        image = capture_screen()
        print(f"截屏成功（{len(image)} 字节）。", flush=True)

        if args.save:
            # 使用排他创建，避免误覆盖文件；仅当前用户可读写（POSIX）。
            fd = os.open(args.save, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(image)
            print(f"截图已保存至：{args.save.resolve()}")

        if args.capture_only:
            print("仅截图模式：未调用 DeepSeek。")
            return 0

        # 截屏完成后打开本机实时页面，避免把页面自身截进去。
        with LiveResult() as view:
            opened = view.open()
            print(f"实时页面：{view.url}", flush=True)
            if not opened:
                print("未能自动打开浏览器，可在生成期间手动打开上面的地址。", flush=True)
            print("正在将截图发送给 DeepSeek，请稍候……\n\n--- 模型答案 ---", flush=True)
            chunks = []
            try:
                for chunk in stream_image(image, api_key):
                    chunks.append(chunk)
                    view.append(chunk)
                    print(chunk, end="", flush=True)
                path = write_result("".join(chunks), args.html)
                print(f"\n\nHTML 结果已保存至：{path}", flush=True)
                view.finish()
            except (CaptureError, DeepSeekError, OSError, ValueError, KeyboardInterrupt) as exc:
                view.finish("已取消。" if isinstance(exc, KeyboardInterrupt) else str(exc))
                if opened:
                    view.wait_for_viewer()
                raise
            if opened:
                view.wait_for_viewer()
        return 0
    except (CaptureError, DeepSeekError, OSError, ValueError) as exc:
        print(f"出错：{exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
