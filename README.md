# 映览 · Yinglan

Python 3.12 / PySide6 Windows x64 图片浏览器。暗黑极简界面：单行顶栏左侧显示名称和「文件、编辑、视图、帮助」菜单，文件名居中，右侧为窗口控制按钮。没有底栏、图片状态信息或独立工具按钮组。

## 使用

从 GitHub Actions 成功运行的 **Yinglan-windows-x64** 产物下载 ZIP，解压后运行 **Yinglan.exe**，无需安装 Python。EXE 未签名；首次启动需解压依赖，可能稍慢。产物保留 30 天。

- **文件**：打开图片、打开文件夹、退出。支持将图片拖入窗口，也可传入命令行文件路径。
- **编辑**：顺时针旋转、复制文件路径。旋转仅改变当前显示，不写入原图片。
- **视图**：上一张、下一张、放大、缩小、适应窗口、原始大小、全屏。
- **帮助**：关于与操作提示。
- 支持 PNG、JPEG、BMP 等当前 Qt 图片插件提供的格式，GIF 显示静态帧。
- 同目录图片按文件名排序并循环切换，自动跳过损坏图片。打开失败时保留当前图片。
- 滚轮缩放，鼠标拖动平移；拖动顶栏移动窗口，双击顶栏最大化或还原，可从窗口边缘调整大小。

| 快捷键 | 功能 |
| --- | --- |
| Ctrl+O | 打开图片 |
| Ctrl+Shift+O | 打开文件夹 |
| 左 / 右方向键 | 上一张 / 下一张 |
| Ctrl+= / Ctrl+- | 放大 / 缩小 |
| Ctrl+0 / Ctrl+1 | 适应窗口 / 原始大小 |
| Ctrl+R | 顺时针旋转 |
| Ctrl+Shift+C | 复制路径 |
| F11 / Esc | 切换全屏 / 退出全屏 |

图片只在本机读取，不上传，也不修改原文件。

## 开发与检查

安装 Python 3.12 x64，在仓库根目录执行 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt -e .
python -m windows_tool
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

也可以直接执行 `.\.venv\Scripts\python.exe`，无需激活虚拟环境。命令行打开图片：`python -m windows_tool "C:\Pictures\photo.jpg"`。

Linux 无显示环境使用 `QT_QPA_PLATFORM=offscreen python -m pytest`。Linux 检查不验证 Windows EXE；请查看对应提交的 Windows Actions 实际结果。

## 项目结构

```text
src/windows_tool/       应用启动、图片视图、自定义顶栏
scripts/entrypoint.py   PyInstaller 入口
tests/                 pytest / pytest-qt 测试
.github/workflows/     Windows CI 构建流程
pyproject.toml         项目、pytest 与 Ruff 配置
requirements*.txt      运行与开发依赖
AGENTS.md              仓库协作约定
```

## Windows 构建

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Yinglan --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtNetwork --paths src scripts/entrypoint.py
```

仅依赖 `PySide6-Essentials`，不安装 Addons；排除未使用的 QML、QtQuick 和网络模块。实际 EXE 大小记录在 Actions 运行摘要中。

每次推送 `main` 或向 `main` 提交 PR，工作流在 `windows-latest` 安装 Python 3.12 x64，检查代码、运行 GUI 测试、打包，并实际启动生成的 EXE，通过 `--smoke-test` 验证 PNG/JPEG 解码、切换、缩放、旋转和文件名更新。通过后才上传 EXE；测试报告单独上传。还可手动运行工作流。

自动化测试不替代真实 Windows 桌面上的人工视觉检查、拖动和窗口边缘操作验证。

## 合并

打开 PR，审核 Files changed，等待 **Test and build Windows x64** 通过，点击 **Squash and merge** 并确认。合并后 `main` 会自动再次测试和打包。
