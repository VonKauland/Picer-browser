"""Compile the small x64 COM bridge with the Windows runner's MSVC toolchain."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(application):
    if sys.platform != "win32":
        raise OSError("The Explorer thumbnail DLL must be built on Windows")
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    installation = subprocess.check_output(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
    ).strip()
    vcvars = Path(installation) / "VC/Auxiliary/Build/vcvarsall.bat"
    if not installation or not vcvars.is_file():
        raise OSError("MSVC x64 C++ build tools are required")
    output = application.resolve() / "shell" / "PicerThumbnail.dll"
    output.parent.mkdir(parents=True, exist_ok=True)
    working = ROOT / "build" / "thumbnail-provider"
    working.mkdir(parents=True, exist_ok=True)
    command = [
        "cl",
        "/nologo",
        "/std:c++17",
        "/O2",
        "/EHsc",
        "/MT",
        "/LD",
        "/W4",
        "/DUNICODE",
        "/D_UNICODE",
        str(ROOT / "native/thumbnail_provider.cpp"),
        "/link",
        "/DEF:" + str(ROOT / "native/thumbnail_provider.def"),
        "/OUT:" + str(output),
        "ole32.lib",
        "shell32.lib",
        "gdi32.lib",
        "uuid.lib",
    ]
    batch = working / "compile.cmd"
    batch.write_text(
        '@echo off\ncall "' + str(vcvars) + '" x64 >nul\n'
        "if errorlevel 1 exit /b %errorlevel%\n" + subprocess.list2cmdline(command) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["cmd.exe", "/d", "/c", str(batch)], cwd=working, check=True)
    if not output.is_file():
        raise OSError("MSVC did not produce the thumbnail provider")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, default=ROOT / "dist/Picer")
    print(build(parser.parse_args().application))
