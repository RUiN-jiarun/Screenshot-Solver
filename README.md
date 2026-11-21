# 局域网截图解答

辅助设备通过浏览器发送请求，主电脑截取主屏幕，使用 DeepSeek 识别并解答，再将答案显示在浏览器中。

## 准备

- 主电脑需要 Python 3.9+、图形桌面和 DeepSeek API Key。macOS 无需安装依赖；Windows / Linux 需运行 `python -m pip install mss`。
- 通过环境变量 `DEEPSEEK_API_KEY` 配置 Key；未设置时，启动服务会提示输入。
- macOS 首次使用时，请在「系统设置 → 隐私与安全性 → 屏幕与系统音频录制」中允许终端录屏。

## 使用

在主电脑的项目目录运行：

```bash
python3 main.py --host 0.0.0.0
```

让辅助设备连接同一局域网，在浏览器打开 `http://<主电脑局域网IP>:8765/`。首次输入终端显示的**访问口令**，以后用同一浏览器和地址访问时，直接点击「截屏并解答」即可。答案会流式显示；模型思考阶段不会显示答案，请耐心等待。macOS 可通过 `ipconfig getifaddr en0` 查看 IP。

服务按 `Ctrl+C` 停止。更新程序后请重启服务并刷新辅助设备网页，避免新旧版本不匹配。访问口令保存在主电脑的 `~/.screen-solver/access-token`；未设置 `SCREEN_SOLVER_TOKEN` 时，停止服务并删除该文件，重启会生成新口令。也可通过该环境变量指定口令。

## 本机调试

无需启动服务或连接辅助设备：

```bash
python3 debug_local.py
```

运行后在 5 秒内切换到题目页面；脚本截取主屏幕并发送给 DeepSeek，答案在终端和自动打开的页面中流式显示（支持 Markdown）。完成后另存独立 HTML 文件，路径显示在终端；实时页面在脚本退出后不能刷新，可打开保存的文件查看。可用 `--delay 10` 调整等待时间，或用 `--html result.html` 指定结果文件。只想检查截图、不调用 API：

```bash
python3 debug_local.py --capture-only --save screenshot.png
```

`--save` 是可选的；截图和 HTML 结果文件均不会自动删除，也不会覆盖已有文件。未指定 HTML 路径时，文件保存在系统临时目录，路径会显示在终端。Markdown 支持标题、列表、表格和代码块，但暂不渲染 LaTeX 公式。

## 演示与测试

```bash
python3 main.py --demo                 # 本机浏览器打开 http://127.0.0.1:8765/
python3 -m unittest discover -s tests -v  # 运行测试
```

演示模式不截屏、不调用 API、不需要 Key。

## 安全提示

- 局域网传输为**明文 HTTP**，仅限可信私人网络使用，不要暴露到互联网。浏览器会保存访问口令，勿在公用设备上使用。
- 每次请求会将**整个主屏幕**发送给 DeepSeek，请先关闭敏感内容。macOS 截图会短暂保存在系统临时目录，之后自动删除。主动保存的截图和 HTML 结果需自行删除。
- 换浏览器、IP 或端口后可能需要重新输入访问口令；访问失败时请检查防火墙及局域网设备隔离设置。
