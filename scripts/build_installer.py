"""Compile a per-user Inno Setup installer from the verified portable folder."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from picer.formats import valid_formats

ROOT = Path(__file__).resolve().parents[1]
TEST_PREFIX = "Software\\PicerInstallerTests\\"


def registry_lines(suffixes, prefix=""):
    if not suffixes or not valid_formats(suffixes):
        raise ValueError("Invalid installer image formats")
    if prefix and not re.fullmatch(re.escape(TEST_PREFIX) + r"[0-9a-f]{32}", prefix):
        raise ValueError("Installer tests require an isolated registry root")
    result = []

    def write(key, name, value, task, kind="string"):
        key = prefix + ("\\" if prefix else "") + key
        value = value.replace('"', '""')
        result.append(
            f'Root: HKCU; Subkey: "{key}"; ValueType: {kind}; '
            f'ValueName: "{name}"; ValueData: "{value}"; Tasks: {task}'
        )

    classes = "Software\\Classes"
    command = '"{app}\\Picer.exe" "%1"'
    icon = '"{app}\\Picer.exe",0'
    progid = classes + "\\Picer.Image"
    application = classes + "\\Applications\\Picer.exe"
    capabilities = "Software\\Picer\\Capabilities"
    for key in (progid, application):
        write(key + "\\DefaultIcon", "", icon, "defaultviewer")
        write(key + "\\shell\\open\\command", "", command, "defaultviewer")
    write(progid, "", "揽映图片", "defaultviewer")
    write(application, "FriendlyAppName", "揽映 Picer", "defaultviewer")
    for suffix in sorted(set(suffixes)):
        write(application + "\\SupportedTypes", suffix, "", "defaultviewer")
        write(capabilities + "\\FileAssociations", suffix, "Picer.Image", "defaultviewer")
        write(classes + "\\" + suffix + "\\OpenWithProgids", "Picer.Image", "", "defaultviewer")
        menu = classes + "\\SystemFileAssociations\\" + suffix + "\\shell\\Picer"
        write(menu, "", "使用揽映打开", "contextmenu")
        write(menu, "Icon", icon, "contextmenu")
        write(menu, "MultiSelectModel", "Single", "contextmenu")
        write(menu + "\\command", "", command, "contextmenu")
    write(capabilities, "ApplicationName", "揽映 Picer", "defaultviewer")
    write(capabilities, "ApplicationDescription", "本地图片与 RAW 照片浏览器", "defaultviewer")
    write(capabilities, "ApplicationIcon", icon, "defaultviewer")
    extensions = "{break}".join(sorted(set(suffixes)))
    write(capabilities, "Extensions", extensions, "defaultviewer", "multisz")
    write("Software\\RegisteredApplications", "Picer", capabilities, "defaultviewer")
    write("Software\\Picer", "ContextExtensions", extensions, "contextmenu", "multisz")
    return "\n".join(result) + "\n"


def compiler_path():
    compiler = shutil.which("ISCC")
    if compiler:
        return Path(compiler)
    candidate = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Inno Setup 6"
        / "ISCC.exe"
    )
    if not candidate.is_file():
        raise OSError("Install Inno Setup 6 before building the Windows installer")
    return candidate


def build(application, output, *, test_root=""):
    if sys.platform != "win32":
        raise OSError("Windows installers must be built on Windows")
    application, output = application.resolve(), output.resolve()
    metadata = json.loads((application / "distribution.json").read_text(encoding="utf-8"))
    if not (application / "Picer.exe").is_file():
        raise OSError("Build and verify the portable application first")
    include = ROOT / "build" / ("installer-test" if test_root else "installer")
    include.mkdir(parents=True, exist_ok=True)
    (include / "registry.iss").write_text(
        registry_lines(metadata["readable_formats"], test_root), encoding="utf-8-sig"
    )
    version = metadata["version"]
    name = f"Picer-{version}-windows-x64-setup" + ("-test" if test_root else "")
    output.mkdir(parents=True, exist_ok=True)
    definitions = {
        "AppVersion": version,
        "SourceDir": str(application),
        "IncludeDir": str(include.resolve()),
        "OutputDir": str(output),
        "OutputName": name,
        "RegistryPrefix": test_root + ("\\" if test_root else ""),
        "FormatList": ";".join(sorted(metadata["readable_formats"])),
        "AppIdentifier": "PicerInstallerTest-" + test_root.rsplit("\\", 1)[-1]
        if test_root
        else "Picer.ImageBrowser",
    }
    command = [str(compiler_path()), *[f"/D{key}={value}" for key, value in definitions.items()]]
    if test_root:
        command.append("/DTestBuild=1")
    script = include / "Picer.iss"
    script.write_text(
        (ROOT / "installer" / "Picer.iss").read_text(encoding="utf-8"), encoding="utf-8-sig"
    )
    subprocess.run([*command, str(script)], check=True)
    result = output / f"{name}.exe"
    if not result.is_file():
        raise OSError("Installer compiler did not produce the expected EXE")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, default=ROOT / "dist" / "Picer")
    parser.add_argument("--output", type=Path, default=ROOT / "release-assets")
    args = parser.parse_args()
    print(build(args.application, args.output))


if __name__ == "__main__":
    main()
