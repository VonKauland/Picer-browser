"""Resource and writable data paths independent of the current working directory."""

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths


@dataclass(frozen=True)
class AppPaths:
    root: Path
    assets: Path
    notice: str = ""

    @property
    def plugins(self) -> Path:
        return self.root / "plugins"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def icon(self) -> Path:
        png = self.assets / "icons" / "picer.png"
        return png if png.is_file() else self.assets / "icons" / "picer.svg"

    def initialize(self) -> None:
        for directory in (self.root, self.plugins, self.cache, self.config, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        # Check actual writes rather than relying on access bits or running as an administrator.
        for directory in (self.root, self.plugins, self.cache, self.config, self.logs):
            with tempfile.TemporaryFile(dir=directory) as file:
                file.write(b"Picer")

    def migrate_legacy(self) -> None:
        """Preserve the old flat configuration when using the same data root."""
        for old, new in (
            (self.root / "plugins.json", self.config / "plugins.json"),
            (self.root / "plugins.log", self.logs / "plugins.log"),
        ):
            if old.is_file() and not new.exists():
                shutil.copy2(old, new)  # Keep the original as a migration backup.

    @classmethod
    def resolve(cls, data_root: Path | None = None) -> "AppPaths":
        frozen = getattr(sys, "frozen", False)
        application = Path(sys.executable).resolve().parent if frozen else Path(__file__).parent
        assets = application / "assets"
        user_root = Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        )
        preferred = (
            Path(data_root).expanduser().resolve()
            if data_root is not None
            else (application if frozen else user_root)
        )
        paths = cls(preferred.resolve(), assets.resolve())
        try:
            paths.initialize()
        except OSError:
            if data_root is not None or preferred.resolve() == user_root.resolve():
                raise
            paths = cls(
                user_root.resolve(),
                assets.resolve(),
                f"应用目录不可写，数据保存到：{user_root.resolve()}",
            )
            paths.initialize()
        paths.migrate_legacy()
        return paths
