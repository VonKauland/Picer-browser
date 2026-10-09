"""Build a complete portable Windows folder, including resources and empty data directories."""

import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

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
        state.write_text(json.dumps({"enabled": {}, "settings": {}}, indent=2), encoding="utf-8")
    with zipfile.ZipFile(
        application / "examples" / "negative-plugin.zip", "w", zipfile.ZIP_DEFLATED
    ) as archive:
        for name in ("manifest.json", "main.py"):
            archive.write(ROOT / "examples" / "negative_plugin" / name, name)
    shutil.copy2(ROOT / "docs" / "plugins.md", application / "docs" / "plugins.md")
    shutil.copy2(ROOT / "docs" / "distribution.md", application / "docs" / "distribution.md")
    (application / "README.txt").write_text(
        "揽映 Picer 图片浏览器\n\n"
        "请保留完整文件夹，双击 Picer.exe 启动，无需安装 Python。\n"
        "plugins：插件；cache：可再生成的缓存；config：设置；logs：日志。\n"
        "assets/icons：图标资源；_internal：必需运行库，请勿删除。\n"
        "插件菜单可安装 examples/negative-plugin.zip 并启用。\n"
        "迁移软件时复制整个目录；更新时保留 plugins 与 config。\n"
        "目录不可写时用户数据退回 LocalAppData/Picer，可从帮助菜单查看位置。\n"
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
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assets = ROOT / "build" / "distribution-assets"
    prepare_icons(ROOT / "src" / "picer" / "assets" / "icons" / "picer.svg", assets / "icons")
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
            "--paths",
            "src",
            "scripts/entrypoint.py",
        ],
        cwd=ROOT,
        check=True,
    )
    prepare_distribution(ROOT / "dist" / "Picer", assets, version=version)


if __name__ == "__main__":
    main()
