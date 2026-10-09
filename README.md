# WindowsTool

基于 Python 3.12、PySide6 的 Windows x64 图片浏览器。

## 图片浏览功能

- 点击“打开图片”或按 `Ctrl+O` 选择图片；支持 PNG、JPEG、BMP、WebP 等当前 Qt 插件支持的格式（GIF 显示静态帧）。
- 自动读取同目录图片，按文件名排序；使用“上一张 / 下一张”或左右方向键切换，首尾循环，自动跳过无法读取的图片。
- 滚轮缩放，按住鼠标左键拖动平移；工具栏支持放大、缩小、适应窗口和原始大小。
- `Ctrl+0` 适应窗口，`Ctrl+1` 原始大小，`Ctrl+=` 放大，`Ctrl+-` 缩小。
- 状态栏显示文件名、图片序号与像素尺寸；打开失败时保留当前图片并显示错误。
- 也可运行 `python -m windows_tool "C:\Pictures\photo.jpg"` 直接打开文件。

图片仅在本机读取，不上传；不修改图片文件。

## 项目结构

```text
src/windows_tool/        应用包、主窗口与启动入口
scripts/entrypoint.py    PyInstaller 入口
tests/                  pytest / pytest-qt 测试
.github/workflows/      Windows CI 构建流程
pyproject.toml          项目、pytest 与 Ruff 配置
requirements.txt        运行依赖
requirements-dev.txt    测试、检查与打包依赖
AGENTS.md               仓库协作约定
```

## Windows 开发

安装 Python 3.12 x64，在仓库根目录执行 PowerShell 命令：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt -e .
python -m windows_tool
```

也可以使用安装后生成的 `windows-tool` 命令。若 PowerShell 限制激活脚本，可直接使用 `.\.venv\Scripts\python.exe` 执行上述命令，无须修改系统策略。

## 自动化检查

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

测试覆盖初始窗口、PNG/JPEG 解码、文件选择、目录切换与循环、损坏文件处理、缩放，以及独立进程中的 GUI 启动与图片浏览。
Linux 无显示环境可运行 `QT_QPA_PLATFORM=offscreen python -m pytest`；Linux 测试通过不代表 Windows EXE 已验证。

## Windows x64 打包

请在 Windows 上使用 Python 3.12 x64：

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WindowsTool --paths src scripts/entrypoint.py
```

生成 `dist/WindowsTool.exe`，可在未安装 Python 的 Windows x64 电脑上启动。`--windowed` 隐藏控制台；`--onefile` 在启动时解压运行依赖，首次启动可能较慢。当前 EXE 未进行代码签名。

## GitHub Actions 与下载

每次推送 `main` 或向 `main` 提交 PR，`Build Windows` 工作流会在 `windows-latest` 上执行：

1. 安装 Python 3.12 x64 和项目依赖。
2. 执行 Ruff 检查、格式检查和 pytest / pytest-qt GUI 测试。
3. 使用 PyInstaller 构建 `WindowsTool.exe`。
4. 启动生成的 EXE，使用 `--smoke-test` 验证 PNG/JPEG 解码、图片切换和缩放，然后检查退出码（超时或非零退出码会让任务失败）。
5. 通过 `actions/upload-artifact` 上传 EXE 和测试报告。

在仓库 **Actions → Build Windows → 成功的运行 → Artifacts** 下载 `WindowsTool-windows-x64`，解压后运行 `WindowsTool.exe`。产物保留 30 天。也可在合并后通过 **Run workflow** 手动构建。

CI 的 EXE 冒烟测试验证启动、图片读取和浏览交互，不替代真实 Windows 桌面上的人工视觉检查。云端 Linux 无法直接验证 Windows EXE；请查看对应提交的 Windows Actions 结果，确认构建、测试和上传步骤是否成功。

## 合并 Pull Request

打开 PR，查看 **Files changed**，等待 **Test and build Windows x64** 检查通过，然后点击 **Squash and merge → Confirm squash and merge**（或仓库允许的其他合并方式）。合并到 `main` 后会再次自动测试并打包。若检查失败，先查看 Actions 日志并修复；若仓库要求审核，请先获得审核批准。
