# Picer 文件夹分发与存储

从 GitHub Releases 下载安装版或便携版，均无需安装 Python。

## 安装版

运行 `Picer-版本号-windows-x64-setup.exe`。默认安装到 `%LOCALAPPDATA%\Programs\Picer`，仅为当前用户安装，无需管理员权限，并创建开始菜单入口。

「选择附加选项」页提供桌面快捷方式、Windows 右键菜单和默认图片浏览器。两个系统集成选项默认不勾选；注册范围仅为当前用户 HKCU。选择默认浏览器后，完成页可以打开 Windows 默认应用设置，由用户确认关联；不改写 UserChoice，也不覆盖其他程序的默认关联。静默安装不会打开系统设置或自动启动应用。Windows 11 的右键入口可能位于「显示更多选项」。

再次安装到同一目录可以升级。安装文件不覆盖 `config`、`plugins`、`skins`、`cache`、`logs` 中的数据；默认组件由程序的可信目录在启动时安装或升级。取消已选集成选项会移除仍指向本安装路径的相应注册项。

从 Windows 已安装的应用列表卸载，或运行安装目录中的 `unins000.exe`。卸载移除程序、快捷方式和本安装目录拥有的注册项，保留配置、用户插件和缓存；若另一份揽映已重新注册，保留那一份的入口。图片源文件不会删除。若需要彻底清理，可在卸载后自行删除保留的数据目录。

## 便携版

下载 `Picer-版本号-windows-x64-portable.zip` 并完整解压，保留整个 `Picer` 文件夹，双击其中的 `Picer.exe` 即可运行。无需管理员权限。`Picer.exe` 依赖同目录的 `_internal`，不能只复制 EXE。

```text
Picer/
  Picer.exe                     启动程序，带应用图标与版本信息
  _internal/                    PyInstaller、Python、Qt 运行库
  assets/icons/                 picer.png、七尺寸透明 picer.ico
  assets/ui/                    透明手柄示意图
  plugins/                      功能与面板组件，随附示例已安装
  skins/                        已安装皮肤组件，默认关闭
  cache/
    thumbnails/                 共享 256px 缩略图，默认最多 4096 项 / 512 MiB
    plugins/<plugin-id>/        插件独立缓存（声明 cache 权限后可使用）
  config/plugins.json           插件启用状态、独立设置
  logs/plugins.log              日志，自动轮转
  examples/                    文件浏览器、图片信息、进度面板、macOS 皮肤 ZIP
    sdk/negative-plugin.zip     负片功能回归示例
  docs/                         插件开发与分发指南
  distribution.json             名称、版本、架构与布局信息
  README.txt                    使用说明
```

缓存子目录与日志文件按需创建。`plugins`、`cache`、`logs` 内的 `.keep` 仅用于让初始 ZIP 保留空目录，可删除。

## 路径规则

- 打包版本默认以 **EXE 所在目录** 为数据根目录，不依赖启动时的工作目录。移动整个文件夹后资源、插件与配置继续可用。
- 源码开发默认使用 Qt 的 `AppLocalDataLocation`，避免在仓库中产生用户数据。
- 应用目录不可写（如放在 Program Files）时，数据退回通常为 `%LOCALAPPDATA%\Picer` 的用户目录；图标仍从应用资源目录读取。插件管理会显示退回原因。
- **帮助 → 打开应用数据目录** 可查看实际保存位置。
- `Picer.exe --data-dir "D:\PicerData"` 可显式指定数据目录。指定目录不可写时启动会报错，不悄悄改用另一个目录。
- `Picer.exe --safe-mode` 本次跳过第三方插件加载，保留设置与插件文件。

## 缓存与资源

图片缩略图缓存以原文件路径、修改时间和大小生成键，内存最多 256 项 / 32 MiB，磁盘默认最多 4096 项 / 512 MiB，可在设置中调整。打开原图依然读取原文件，磁盘缓存只服务预览缩略图。**帮助 → 清理图片缓存** 清理宿主解码与缩略图缓存，不删除插件、原图或插件设置。插件通过 `context.request_thumbnail()` 共享异步缩略图服务，也保留 `context.thumbnail()` 同步接口；通过 `context.cache_directory()` 获取独立缓存目录，插件应自行控制其缓存体积。

图标资源以透明 `assets/icons/picer.png` 为源，在 Windows 构建时生成 PNG 和七尺寸 ICO，保留外发光与内部深色像素。ICO 同时嵌入 EXE，窗口、顶栏和资源目录使用同一图标。

## 从旧版本迁移

旧单文件版本的数据通常在 `%LOCALAPPDATA%\Picer`：

1. 关闭旧版及新版应用。
2. 将旧数据目录中的 `plugins/` 复制到新版 `Picer/plugins/`。
3. 将旧 `plugins.json` 复制到新版 `Picer/config/plugins.json`，如需保留旧日志，复制到 `Picer/logs/`。
4. 启动新版并检查插件状态。仅迁移可信插件。

如果继续使用原数据根目录（例如通过 `--data-dir` 指定），程序会把旧的顶层 `plugins.json` 和 `plugins.log` 复制到新的 `config`、`logs` 子目录；已存在的新文件不会覆盖，原文件保留为备份。

## 更新、备份与卸载

- 更新：先关闭程序，解压新版到一个新目录，再从旧目录复制 `plugins`、`skins` 和 `config`。可选复制 `logs`；缓存无需备份。避免用新包的默认配置覆盖已有设置。
- 备份与迁移：复制整个应用目录即可；若数据曾退回用户目录或通过参数指定，还需复制实际数据目录。
- 清理：关闭应用后可删除缓存内容，下次会重新生成缩略图。
- 卸载：若已手动注册资源管理器右键菜单，请先在系统设置中取消注册，再关闭程序并删除应用目录；另行删除实际退回/指定的数据目录即可移除用户数据。默认图片浏览器的选择由 Windows 默认应用设置管理，程序不自动改写默认关联。

## 构建与验证

在 Windows Python 3.12 x64 环境中执行：

```powershell
python -m scripts.build_windows
python -m scripts.verify_distribution
python -m scripts.build_installer
python -m scripts.verify_installer
python -m scripts.release_assets
```

构建使用 PyInstaller `--onedir --windowed --contents-directory _internal`，输出 `dist/Picer/`，再复制图标、示例插件、文档和数据目录。

体积优化移除 PyInstaller 自动带入的 `PySide6/opengl32sw.dll`、未使用的 `qdirect2d.dll` 和 Qt 自带的非中英文翻译目录文件。宿主使用默认 Windows 平台的 QWidget/QGraphicsView 光栅视口，不使用 OpenGL 或 Direct2D 平台插件；保留 `qwindows`、离屏后端、中英文翻译、Python、Qt 主库、全部图片插件及 RAW/NumPy/FFmpeg 库。未知翻译模块和第三方插件资源不会被清理。ZIP 使用 Deflate 最高压缩级别，解压后的文件不变。`build/distribution-size.json` 记录清理前后每个文件的体积和明确移除项，构建日志同时输出文件清单。实际 EXE 校验构建时记录的格式集合，逐项解码可用的静态图片，并执行 RAW、动画与界面测试；不把删除文件本身视为验证通过。

Windows CI 在临时目录复制完整软件，从无关工作目录启动 EXE，执行图片、三类组件、快捷位与全屏面板冒烟测试，检查实际配置、日志和缓存写入位置，然后迁移整个文件夹并再次启动，确认插件设置保留。最终上传原始干净的 `dist/`，测试写入的数据不会包含在分发包内。

安装包由 Inno Setup 6 在 Windows 编译。CI 对公开安装包执行安装、实际 EXE 启动/重启、升级和卸载，并对同一脚本/完整载荷的隔离注册表测试构建执行四种勾选组合，检查其他默认关联与另一份揽映的注册项保留。测试不会打开系统默认应用页面，也不模拟用户修改默认关联。

包含 `[release]` 标记的 main 提交只有在完整构建和安装验证通过后，才通过单独具有 contents:write 权限的发布作业创建 Release：先创建草稿，上传便携 ZIP、安装 EXE 与 SHA256SUMS.txt，全部成功后发布。普通提交和 PR 不自动发布。
