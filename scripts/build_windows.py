"""Build a complete portable Windows folder, including resources and empty data directories."""

import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

from picer.bundles import EXAMPLES, write_examples
from picer.imaging import supported_suffixes
from scripts.distribution_size import compact_distribution
from scripts.prepare_assets import prepare_icons

ROOT = Path(__file__).resolve().parents[1]


def prepare_distribution(application: Path, assets: Path, *, version: str) -> None:
    if not (application / "Picer.exe").is_file() or not (application / "_internal").is_dir():
        raise RuntimeError("The PyInstaller onedir application is incomplete")
    shutil.copytree(assets, application / "assets", dirs_exist_ok=True)
    for name in ("plugins", "cache", "config", "logs", "examples", "docs"):
        directory = application / name
        directory.mkdir(parents=True, exist_ok=True)
        if name in {"plugins", "cache", "logs"}:
            (directory / ".keep").write_text("", encoding="utf-8")
    state = application / "config" / "plugins.json"
    if not state.exists():
        state.write_text(
            json.dumps(
                {
                    "enabled": {plugin_id: enabled for _, _, plugin_id, enabled in EXAMPLES},
                    "settings": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    write_examples(application / "examples")
    for _, filename, plugin_id, _ in EXAMPLES:
        destination = (
            application / ("skins" if plugin_id == "example.macos" else "plugins") / plugin_id
        )
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(application / "examples" / filename) as archive:
            archive.extractall(destination)
    for name in (
        "plugins",
        "distribution",
        "components",
        "example-components",
        "media",
        "input",
        "settings",
    ):
        shutil.copy2(ROOT / "docs" / f"{name}.md", application / "docs" / f"{name}.md")
    (application / "README.txt").write_text(
        "揽映 Picer 图片浏览器\n\n"
        "请保留完整文件夹，双击 Picer.exe 启动，无需安装 Python。\n"
        "plugins：功能与面板组件；skins：已安装皮肤；cache：可再生成的缓存；config：设置；logs：日志。\n"
        "assets/icons：图标资源；_internal：必需运行库，请勿删除。\n"
        "examples 提供文件浏览器、图片信息、浏览进度及 macOS 皮肤。\n"
        "启动时默认安装；图片管理、简易编辑及皮肤默认关闭，其他面板与功能默认启用。\n"
        "顶栏 5 个快捷位可右键配置；毛玻璃面板隐藏后悬停边缘细条即可展开。\n"
        "三点条右键自动隐藏，侧面板拖动调宽、Shift 拖动左右换边。\n"
        "点击隐藏细条靠边固定；侧面板拖动细条左右换边并保持隐藏。\n"
        "文件浏览器支持列表 / 平铺，均带图片预览；窄信息面板自动换行。\n"
        "进度条拖动实时切图；缩略预览再次按弹出按钮关闭，控制面板隐藏后贴近底部。\n"
        "底部只允许一个进度面板，居中占窗口宽度约 1/3；缩略预览无底板、无滚动条。\n"
        "组件设置统一位于插件管理的设置页；三个默认示例面板不提供设置按钮。\n"
        "选项 → 系统设置：常规、外观、图片浏览、面板布局、快捷键、缓存与存储。\n"
        "应用保存后保持设置窗口打开，保存更改后关闭；恢复默认需确认。\n"
        "选项菜单可导出 / 导入系统设置 JSON，导入后检查表单并点击应用。\n"
        "迁移软件时复制整个目录；更新时保留 plugins、skins 与 config。\n"
        "目录不可写时用户数据退回 LocalAppData/Picer，可从帮助菜单查看位置。\n"
        "支持 LibRaw 相机 RAW、GIF/WebP 动画；动画帧进度位于图片进度条下方。\n"
        "大图使用后台预览和原图替换，完整格式与性能边界见 docs/media.md。\n"
        "启动排障：Picer.exe --safe-mode。详细指南见 docs。\n",
        encoding="utf-8",
    )
    (application / "distribution.json").write_text(
        json.dumps(
            {
                "name": "Picer",
                "display_name": "揽映",
                "version": version,
                "architecture": "x64",
                "mode": "portable-folder",
                "plugin_api": 1,
                "component_types": ["skin", "function", "panel"],
                "readable_formats": sorted(supported_suffixes()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def version_resource(version: str) -> str:
    parts = tuple(int(part) for part in version.split(".")) + (0,)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0,
                   OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', '揽映 Picer 图片浏览器'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('InternalName', 'Picer'),
    StringStruct('OriginalFilename', 'Picer.exe'),
    StringStruct('ProductName', '揽映 Picer'),
    StringStruct('ProductVersion', '{version}')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)"""


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows EXE builds must run on Windows")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assets = ROOT / "build" / "distribution-assets"
    prepare_icons(ROOT / "src" / "picer" / "assets" / "icons" / "picer.png", assets / "icons")
    shutil.copytree(ROOT / "src" / "picer" / "assets" / "ui", assets / "ui", dirs_exist_ok=True)
    bundles = assets.parent / "trusted-bundles"
    write_examples(bundles)
    resource = assets.parent / "version-info.txt"
    resource.write_text(version_resource(version), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--contents-directory",
            "_internal",
            "--name",
            "Picer",
            "--icon",
            str(assets / "icons" / "picer.ico"),
            "--version-file",
            str(resource),
            "--exclude-module",
            "PySide6.QtQml",
            "--exclude-module",
            "PySide6.QtQuick",
            "--exclude-module",
            "PySide6.QtNetwork",
            "--collect-submodules",
            "picer.editing",
            "--hidden-import",
            "ctypes.wintypes",
            "--hidden-import",
            "picer.file_drag",
            "--copy-metadata",
            "rawpy",
            "--copy-metadata",
            "numpy",
            "--copy-metadata",
            "ExifRead",
            "--copy-metadata",
            "av",
            "--add-data",
            str(bundles) + ";picer/bundles",
            "--paths",
            "src",
            "scripts/entrypoint.py",
        ],
        cwd=ROOT,
        check=True,
    )
    prepare_distribution(ROOT / "dist" / "Picer", assets, version=version)
    report = compact_distribution(ROOT / "dist" / "Picer")
    (assets.parent / "distribution-size.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Distribution: {report['before']['bytes']} -> {report['after']['bytes']} bytes; "
        f"saved {report['saved_bytes']} bytes; removed {report['removed']}"
    )
    print("DISTRIBUTION_INVENTORY=" + json.dumps(report["after"], separators=(",", ":")))


if __name__ == "__main__":
    main()
