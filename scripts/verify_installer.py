"""Real installer/upgrade/uninstall checks; integration uses isolated native HKCU."""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from picer.windows_integration import CAPABILITIES, PROG_ID, WindowsIntegration
from scripts.build_installer import ROOT, TEST_PREFIX, build
from scripts.verify_distribution import run_smoke


class InstallerWorkspace(tempfile.TemporaryDirectory):
    """Inno's final self-deletion process can briefly retain its uninstall log."""

    def cleanup(self):
        deadline = time.monotonic() + 10
        while True:
            try:
                return super().cleanup()
            except PermissionError as error:
                if getattr(error, "winerror", None) not in {5, 32} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)


def run(command, log):
    result = subprocess.run(command, timeout=180, check=False)
    if result.returncode != 0:
        content = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        print(content.encode("ascii", errors="backslashreplace").decode("ascii"))
        raise RuntimeError(f"Installer command failed: {result.returncode}")


def install(setup, destination, tasks, log):
    run(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            f"/DIR={destination}",
            f"/TASKS={tasks}",
            f"/LOG={log}",
        ],
        log,
    )


def uninstall(destination, log):
    uninstaller = destination / "unins000.exe"
    if not uninstaller.is_file():
        raise RuntimeError("The installer did not create an uninstaller")
    run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}"], log)
    if (destination / "Picer.exe").exists():
        raise RuntimeError("Uninstall failed to remove the installed EXE")


def verify_payload(application, destination):
    """User-data exclusions must never omit nested Qt plugins or other libraries."""
    user_directories = {"config", "plugins", "skins", "cache", "logs"}
    checked = 0
    for source in application.rglob("*"):
        relative = source.relative_to(application)
        if not source.is_file() or relative.parts[0] in user_directories:
            continue
        target = destination / relative
        if not target.is_file():
            raise RuntimeError(f"Installer omitted runtime file: {relative}")
        with source.open("rb") as before, target.open("rb") as after:
            if (
                hashlib.file_digest(before, "sha256").digest()
                != hashlib.file_digest(after, "sha256").digest()
            ):
                raise RuntimeError(f"Installed file differs from verified build: {relative}")
        checked += 1
    print(f"Installed payload matches verified portable build: {checked} files", flush=True)


def verify(application, setup):
    import winreg

    metadata = json.loads((application / "distribution.json").read_text(encoding="utf-8"))
    suffixes = metadata["readable_formats"]
    with InstallerWorkspace(prefix="picer-setup-check-") as temporary:
        root = Path(temporary).resolve()
        destination = root / "揽映 安装 path with spaces"
        work = root / "unrelated-cwd"
        work.mkdir()
        images = root / "images"
        images.mkdir()
        # Exercise the exact public installer, with integrations left off.
        install(setup, destination, "", root / "production-install.log")
        verify_payload(application, destination)
        if not (destination / "assets" / "ui" / "gamepad.png").is_file():
            raise RuntimeError("Installer resources are incomplete")
        run_smoke(destination, work, images)
        state = destination / "config" / "plugins.json"
        before = state.read_bytes()
        user_plugin = destination / "plugins" / "user-owned.txt"
        user_plugin.write_text("preserve this plugin", encoding="utf-8")
        install(setup, destination, "", root / "production-upgrade.log")
        verify_payload(application, destination)
        if state.read_bytes() != before or user_plugin.read_text() != "preserve this plugin":
            raise RuntimeError("Upgrade changed user settings or plugins")
        run_smoke(destination, work, images)
        before = state.read_bytes()
        uninstall(destination, root / "production-uninstall.log")
        if state.read_bytes() != before or not user_plugin.is_file():
            raise RuntimeError("Uninstall deleted user data")
        print(
            "Public installer: install, actual EXE/restart, upgrade, "
            "user-data preservation and uninstall passed",
            flush=True,
        )

        prefix = TEST_PREFIX + uuid4().hex
        test_setup = build(application, root / "compiled-test", test_root=prefix)
        service = WindowsIntegration(setup, root=prefix)
        # Preserve another viewer and the OS-owned default selection.
        service.write(r"Software\Classes\.png", "", "OtherViewer.Image")
        choice = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.png\UserChoice"
        service.write(choice, "ProgId", "OtherViewer.Image")
        try:
            for number, tasks in enumerate(
                ("", "contextmenu", "defaultviewer", "contextmenu,defaultviewer")
            ):
                target = root / f"选项 {number}"
                install(test_setup, target, tasks, root / f"options-{number}.log")
                command = f'"{target / "Picer.exe"}" "%1"'
                context = service.read(service.menu_key(".png") + r"\command", "")
                viewer = service.read(r"Software\Classes\Picer.Image\shell\open\command", "")
                if context != (command if "contextmenu" in tasks else None):
                    raise RuntimeError("Context-menu checkbox was not respected")
                if viewer != (command if "defaultviewer" in tasks else None):
                    raise RuntimeError("Default-viewer checkbox was not respected")
                if "defaultviewer" in tasks:
                    for suffix in suffixes:
                        if service.read(CAPABILITIES + r"\FileAssociations", suffix) != PROG_ID:
                            raise RuntimeError("Installer missed a supported format")
                if (
                    service.read(r"Software\Classes\.png", "") != "OtherViewer.Image"
                    or service.read(choice, "ProgId") != "OtherViewer.Image"
                ):
                    raise RuntimeError("Installer overwrote another default viewer")
                if number == 3:
                    # A newer portable registration must survive uninstalling this copy.
                    other = root / "another-copy.exe"
                    other.touch()
                    alternate = WindowsIntegration(other, root=prefix)
                    alternate.register_viewer([".png"])
                    alternate.register_context_menu([".png"])
                uninstall(target, root / f"options-{number}-uninstall.log")
                if number == 3:
                    if (
                        service.read(r"Software\Classes\Picer.Image\shell\open\command", "")
                        != alternate.command
                    ):
                        raise RuntimeError(
                            "Uninstall removed another Picer copy's viewer registration"
                        )
                    if (
                        service.read(service.menu_key(".png") + r"\command", "")
                        != alternate.command
                    ):
                        raise RuntimeError("Uninstall removed another Picer copy's context menu")
                elif (
                    service.read(service.menu_key(".png"), "") is not None
                    or service.read(CAPABILITIES, "ApplicationName") is not None
                ):
                    raise RuntimeError("Uninstall left owned integration keys")
                if service.read(choice, "ProgId") != "OtherViewer.Image":
                    raise RuntimeError("Uninstall changed UserChoice")
            print(
                "Four checkbox combinations, all formats, quoted paths and "
                "ownership-safe uninstall passed (isolated HKCU)",
                flush=True,
            )
        finally:
            service.delete("")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, prefix):
                raise RuntimeError("Installer registry test root was not removed")
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Actual installer verification requires Windows")
    application = ROOT / "dist" / "Picer"
    version = json.loads((application / "distribution.json").read_text(encoding="utf-8"))["version"]
    verify(application, ROOT / "release-assets" / f"Picer-{version}-windows-x64-setup.exe")
