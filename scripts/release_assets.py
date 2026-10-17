"""Archive the complete portable folder and record public release checksums."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def archive_portable(application, output):
    metadata = json.loads((application / "distribution.json").read_text(encoding="utf-8"))
    if not (application / "Picer.exe").is_file():
        raise ValueError("The portable application is incomplete")
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"Picer-{metadata['version']}-windows-x64-portable.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(application.rglob("*")):
            if file.is_file():
                archive.write(file, (Path("Picer") / file.relative_to(application)).as_posix())
    return target


def checksums(output):
    files = sorted([*output.glob("*-portable.zip"), *output.glob("*-setup.exe")])
    if len(files) != 2:
        raise ValueError("Release requires exactly one portable ZIP and one installer EXE")
    rows = []
    for file in files:
        with file.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        rows.append(f"{digest}  {file.name}\n")
    (output / "SHA256SUMS.txt").write_text("".join(rows), encoding="utf-8")


if __name__ == "__main__":
    destination = ROOT / "release-assets"
    print(archive_portable(ROOT / "dist" / "Picer", destination))
    checksums(destination)
