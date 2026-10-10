"""Provision the application-shipped examples, preserving subsequent user choices."""

import sys
import tempfile
import zipfile
from pathlib import Path

from picer.plugins.api import PluginError
from picer.plugins.manifest import Manifest

EXAMPLES = (
    ("file_browser", "file-browser.zip", "example.files", True),
    ("info_panel", "info-panel.zip", "example.info", True),
    ("progress_panel", "progress-panel.zip", "example.progress", True),
    ("macos_skin", "macos-skin.zip", "example.macos", False),
    ("negative_plugin", "sdk/negative-plugin.zip", "example.negative", True),
)


def write_examples(destination):
    source = Path(__file__).resolve().parents[2] / "examples"
    for directory, filename, _, _ in EXAMPLES:
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted((source / directory).iterdir()):
                if file.is_file():
                    archive.write(file, file.name)


def seed_examples(manager):
    """Only the shipped catalog gets defaults; arbitrary installed ZIPs stay disabled.

    Record provisioning separately from enable preferences so disabling or uninstalling
    an example survives restart. Upgrade shipped versions without resetting settings.
    """
    markers = manager.preferences["ui"].get("bundled_examples", {})
    if not isinstance(markers, dict):
        markers = {}
    manager.preferences["ui"]["bundled_examples"] = markers
    with tempfile.TemporaryDirectory(prefix="picer-bundles-") as temporary:
        if getattr(sys, "frozen", False):
            source = Path(sys._MEIPASS) / "picer" / "bundles"
        else:
            source = Path(temporary)
            write_examples(source)
        for _, filename, plugin_id, enabled in EXAMPLES:
            archive = source / filename
            try:
                with zipfile.ZipFile(archive) as package:
                    metadata = Path(temporary) / "manifest.json"
                    metadata.write_bytes(package.read("manifest.json"))
                    manifest = Manifest.read(metadata)
                if manifest.id != plugin_id:
                    raise PluginError("随应用分发的示例 id 与目录不匹配")
                previous = manager.records.get(plugin_id)
                if previous is None and plugin_id in markers:
                    continue  # An explicit uninstall is not undone on restart.
                if previous and previous.manifest.version == manifest.version:
                    markers.setdefault(plugin_id, manifest.version)
                    continue
                if previous and tuple(map(int, previous.manifest.version.split("."))) > tuple(
                    map(int, manifest.version.split("."))
                ):
                    continue
                wanted = manager.preferences["enabled"].get(plugin_id, enabled)
                manager.install(archive, replace_existing=previous is not None)
                manager.preferences["enabled"][plugin_id] = wanted
                markers[plugin_id] = manifest.version
            except (OSError, KeyError, zipfile.BadZipFile, PluginError) as error:
                manager.diagnostics.append(f"默认示例 {plugin_id}：{error}")
