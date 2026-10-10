# 揽映 · Picer

Python 3.12 / PySide6 Windows x64 图片浏览器，以可扩展插件系统为核心。暗黑极简界面：单行顶栏左侧显示名称和「文件、编辑、视图、插件、帮助」菜单，文件名居中，右侧为 5 个精致功能快捷位与窗口控制按钮。没有底栏、图片状态信息或独立工具按钮组。

## 使用

从 GitHub Actions 成功运行的 **Picer-windows-x64** 产物下载 ZIP，完整解压后进入 **Picer/** 并运行 **Picer.exe**，无需安装 Python。必须保留同目录的 `_internal` 和资源文件；EXE 未签名。产物保留 30 天。

- **文件**：打开图片、打开文件夹、退出。支持将图片拖入窗口，也可传入命令行文件路径。
- **编辑**：顺时针旋转、复制文件路径。旋转仅改变当前显示，不写入原图片。
- **视图**：上一张、下一张、放大、缩小、适应窗口、原始大小、全屏。
- **插件**：组件管理与设置、皮肤单选、功能启停、面板启停与隐藏、功能调用及快捷栏位配置。
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

宿主及随附插件只处理本地图片预览，不上传或修改原文件。第三方插件的行为由其代码决定。

## 插件核心

- 旋转、水平翻转与灰度预览由可启停的内置插件提供。
- 第三方插件通过版本化 SDK 扩展菜单命令、图片处理、事件、独立设置与后台任务。
- 插件管理入口：**插件 → 插件管理**，快捷键 `Ctrl+Shift+P`。
- 软件文件夹 `examples/` 提供文件浏览器、图片信息、浏览进度面板及 macOS 皮肤；详见 [示例组件说明](docs/example-components.md)。
- 新插件默认停用；第三方 Python 插件需来自可信来源。错误记录在插件管理及日志中。
- 启动排障：`Picer.exe --safe-mode`，跳过本次第三方插件加载。

三类组件规范、快捷位与面板显示规则见 [组件开发规则](docs/components.md)。

面板统一采用无标题、无外边框的毛玻璃外壳。内侧居中的三点条用于拖动调宽/调高，右键可自动隐藏或换边，Shift 拖动可移动已固定面板。隐藏后悬停细长边缘条展开，离开收回；点击细条靠边固定，拖动细条可在左、右、底部换边并保持隐藏。位置和尺寸随配置保存。

窗口右上角统一使用同尺寸的黄色最小化、绿色最大化、红色关闭细线按钮，包括 macOS 皮肤。皮肤仅作用于宿主，不改动插件图标和内容样式。

完整架构、清单格式、API、生命周期与扩展边界见 [插件开发文档](docs/plugins.md)，完整示例见 [negative_plugin](examples/negative_plugin)。

## 完整软件文件夹

```text
Picer/
  Picer.exe             启动程序
  _internal/            Python / Qt 运行库
  assets/icons/         应用 SVG、PNG、ICO 图标
  plugins/              功能与面板组件
  skins/                已安装皮肤（首次安装后创建）
  cache/                缩略图与插件缓存
  config/               插件配置
  logs/                 轮转日志
  examples/             三个面板与 macOS 皮肤 ZIP；sdk/ 为回归示例
  docs/                 使用与插件开发指南
  README.txt            快速说明
  distribution.json     分发版本与架构信息
```

默认数据与软件保存在同一文件夹，移动整个目录后仍可使用。目录不可写时退回用户数据目录；通过 **帮助 → 打开应用数据目录** 查看实际位置。`--data-dir` 可指定其他数据目录，**帮助 → 清理图片缓存** 可释放宿主缩略图缓存。

更新时请解压到新目录，再迁移原 `plugins`、`skins` 与 `config`；旧单文件版的迁移步骤见 [文件夹分发指南](docs/distribution.md)。

## 开发与检查

安装 Python 3.12 x64，在仓库根目录执行 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt -e .
python -m picer
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

也可以直接执行 `.\.venv\Scripts\python.exe`，无需激活虚拟环境。命令行打开图片：`python -m picer "C:\Pictures\photo.jpg"`。

Linux 无显示环境使用 `QT_QPA_PLATFORM=offscreen python -m pytest`。Linux 检查不验证 Windows EXE；请查看对应提交的 Windows Actions 实际结果。

## 项目结构

```text
src/picer/             应用启动、图片视图、自定义顶栏
src/picer/plugins/     插件 SDK、加载器、管理界面与内置插件
examples/              第三方插件示例
docs/plugins.md        插件架构与开发指南
scripts/entrypoint.py   PyInstaller 入口
tests/                 pytest / pytest-qt 测试
.github/workflows/     Windows CI 构建流程
pyproject.toml         项目、pytest 与 Ruff 配置
requirements*.txt      运行与开发依赖
AGENTS.md              仓库协作约定
```

## Windows 构建

```powershell
python -m scripts.build_windows
python -m scripts.verify_distribution
```

构建脚本采用 PyInstaller `--onedir --windowed --contents-directory _internal`，输出完整 `dist/Picer/`。构建时生成应用图标与 EXE 版本信息，复制文档、示例插件和数据目录。仅依赖 `PySide6-Essentials`，排除未使用的 QML、QtQuick 和网络模块。

每次推送 `main` 或向 `main` 提交 PR，工作流在 `windows-latest` 安装 Python 3.12 x64，检查代码、运行 GUI 测试、构建，并在临时目录复制完整软件后启动实际 EXE。它验证四个主要示例、EXIF/直方图、进度与预览、五个快捷位、全屏、悬停展开、隐藏条拖动/固定、三点拖拽条以及缓存/配置/日志位置，并将整个文件夹迁移后再次启动，确认设置保留。验证成功后上传完整目录，测试数据不进入最终分发包；测试报告单独上传。还可手动运行工作流。

自动化测试不替代真实 Windows 桌面上的人工视觉检查、拖动和窗口边缘操作验证。

## 合并

打开 PR，审核 Files changed，等待 **Test and build Windows x64** 通过，点击 **Squash and merge** 并确认。合并后 `main` 会自动再次测试和打包。
