"""Registry scope, optional tasks and complete portable release archives."""

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from scripts.build_installer import TEST_PREFIX, registry_lines
from scripts.release_assets import archive_portable, checksums
from scripts.verify_installer import InstallerWorkspace, verify_payload


def test_registration_catalog_is_per_user_quoted_and_task_scoped():
    text = registry_lines([".png", ".jpg", ".dng"])
    lines = text.splitlines()
    assert all(line.startswith("Root: HKCU;") for line in lines)
    assert all("Tasks: contextmenu" in line or "Tasks: defaultviewer" in line for line in lines)
    assert 'ValueData: """{app}\\Picer.exe"" ""%1"""' in text
    assert "UserChoice" not in text and "HKLM" not in text
    assert 'Subkey: "Software\\Classes\\.png";' not in text
    for suffix in (".png", ".jpg", ".dng"):
        assert f"SystemFileAssociations\\{suffix}\\shell\\Picer" in text
        assert f'ValueName: "{suffix}"; ValueData: "Picer.Image"' in text


@pytest.mark.parametrize("suffixes", [[], [".PNG"], ["png"], [".png\\shell"]])
def test_invalid_extension_cannot_become_a_registry_path(suffixes):
    with pytest.raises(ValueError):
        registry_lines(suffixes)


def test_test_registry_isolation_is_strict():
    prefix = TEST_PREFIX + "a" * 32
    lines = registry_lines([".png"], prefix).splitlines()
    assert all(f'Subkey: "{prefix}\\' in line for line in lines)
    for invalid in ("Software\\Classes", TEST_PREFIX + "..", "HKLM"):
        with pytest.raises(ValueError):
            registry_lines([".png"], invalid)


def test_installer_options_preserve_user_data_and_os_confirmation():
    script = (Path(__file__).parents[1] / "installer" / "Picer.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in script
    assert 'Excludes: "\\config\\*,\\plugins\\*,\\skins\\*,\\cache\\*,\\logs\\*"' in script
    for task in ("contextmenu", "defaultviewer"):
        line = next(line for line in script.splitlines() if line.startswith(f'Name: "{task}"'))
        assert "Flags: unchecked" in line
    assert 'Filename: "ms-settings:defaultapps?registeredAppUser=Picer"' in script
    assert "postinstall skipifsilent" in script
    assert "OwnCommand" in script and "CurUninstallStepChanged" in script
    assert "UserChoice" not in script and "HKEY_LOCAL_MACHINE" not in script


def test_portable_zip_contains_complete_folder_and_checksums(tmp_path):
    application = tmp_path / "application"
    for name, content in {
        "Picer.exe": b"test layout, not a binary",
        "_internal/Qt.dll": b"runtime",
        "assets/icons/picer.png": b"icon",
        "plugins/.keep": b"",
        "config/plugins.json": b"{}",
        "distribution.json": json.dumps({"version": "0.21.0"}).encode(),
    }.items():
        file = application / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    output = tmp_path / "output"
    portable = archive_portable(application, output)
    with zipfile.ZipFile(portable) as archive:
        assert archive.read("Picer/_internal/Qt.dll") == b"runtime"
        assert archive.read("Picer/config/plugins.json") == b"{}"
        assert "Picer/plugins/.keep" in archive.namelist()
    with pytest.raises(ValueError):
        checksums(output)
    installer = output / "Picer-0.21.0-windows-x64-setup.exe"
    installer.write_bytes(b"test layout")
    checksums(output)
    for file in (portable, installer):
        assert (
            f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}"
            in (output / "SHA256SUMS.txt").read_text()
        )


def test_installed_payload_requires_nested_qt_plugins_but_preserves_user_data(tmp_path):
    source, installed = tmp_path / "source", tmp_path / "installed"
    for name, content in {
        "Picer.exe": b"layout fixture",
        "_internal/PySide6/plugins/platforms/qwindows.dll": b"platform library",
        "_internal/PySide6/plugins/imageformats/qwebp.dll": b"image codec",
        "plugins/user/main.py": b"new defaults must not overwrite user plugin",
        "config/plugins.json": b"new defaults must not overwrite user settings",
    }.items():
        for base in (source, installed):
            file = base / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
    (installed / "config/plugins.json").write_bytes(b"personal settings")
    (installed / "plugins/user/main.py").write_bytes(b"personal plugin")
    verify_payload(source, installed)
    platform = installed / "_internal/PySide6/plugins/platforms/qwindows.dll"
    platform.unlink()
    with pytest.raises(RuntimeError, match="omitted runtime"):
        verify_payload(source, installed)
    platform.write_bytes(b"corrupted platform")
    with pytest.raises(RuntimeError, match="differs from verified"):
        verify_payload(source, installed)


def test_installer_workspace_retries_only_transient_windows_sharing_errors(monkeypatch):
    cleanup = tempfile.TemporaryDirectory.cleanup
    attempts = []

    def briefly_locked(self):
        attempts.append(1)
        if len(attempts) < 3:
            error = PermissionError("uninstall log still open")
            error.winerror = 32
            raise error
        return cleanup(self)

    with monkeypatch.context() as patch:
        patch.setattr(tempfile.TemporaryDirectory, "cleanup", briefly_locked)
        patch.setattr("scripts.verify_installer.time.sleep", lambda _: None)
        with InstallerWorkspace() as temporary:
            path = Path(temporary)
            (path / "uninstall.log").write_text("test log")
        assert len(attempts) == 3 and not path.exists()

    workspace = InstallerWorkspace()
    with monkeypatch.context() as patch:

        def forbidden(self):
            raise PermissionError("persistent non-sharing permission failure")

        patch.setattr(tempfile.TemporaryDirectory, "cleanup", forbidden)
        with pytest.raises(PermissionError, match="non-sharing"):
            workspace.cleanup()
    workspace.cleanup()
