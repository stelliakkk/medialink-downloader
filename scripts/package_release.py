"""Package the verified EXE, committed project source and upstream source material."""

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from release_sources import CACHE, ROOT, sha256


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def collect_licenses(destination: Path, sources: list[dict]):
    expression = re.compile(r"^(?:licen[cs]e(?:[^/]*\.(?:txt|md|rst))?|copying[^/]*|copyright[^/]*|notice(?:\.[^/]*)?)$", re.I)
    for entry in sources:
        archive = CACHE / entry["file"]
        component = re.sub(r"\.(?:tar\.(?:gz|xz)|tgz)$", "", archive.name)
        with tarfile.open(archive) as package:
            for member in package:
                path = PurePosixPath(member.name)
                parts = path.parts[1:]
                if not member.isfile() or member.size > 2 * 1024 * 1024 or not parts or ".." in parts:
                    continue
                in_licenses = any(p.lower() == "licenses" for p in parts[:-1])
                if not in_licenses and not expression.fullmatch(parts[-1]):
                    continue
                stream = package.extractfile(member)
                if stream is None:
                    continue
                target = destination / component / Path(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)


def main():
    if git("status", "--porcelain"):
        raise SystemExit("Commit the exact release source before packaging.")
    version = re.search(r'__version__ = "([0-9.]+)"', (ROOT / "src/medialink/__init__.py").read_text("utf-8"))[1]
    name = f"MediaLinkDownloader-v{version}"
    folder = ROOT / "dist" / name
    executable = folder / "MediaLinkDownloader.exe"
    if not executable.is_file():
        raise SystemExit("Build and verify the executable first.")
    commit = git("rev-parse", "HEAD")
    entries = json.loads((CACHE / "manifest.json").read_text("utf-8"))
    if not entries or not any(e["file"].startswith("ffmpeg-") for e in entries):
        raise SystemExit("Upstream source manifest is incomplete.")
    for entry in entries:
        if sha256(CACHE / entry["file"]) != entry["sha256"]:
            raise SystemExit(f"Source archive checksum mismatch: {entry['file']}")
    source_zip = ROOT / "dist" / f"{name}-source.zip"
    subprocess.run(["git", "archive", "--format=zip", "--prefix=" + name + "-source/", "-o", str(source_zip), commit],
                   cwd=ROOT, check=True)
    upstream_zip = ROOT / "dist" / f"{name}-third-party-sources.zip"
    with ZipFile(upstream_zip, "w", compression=ZIP_STORED) as output:
        output.writestr("manifest.json", json.dumps(entries, indent=2) + "\n")
        output.write(ROOT / "runtime/README.txt", "ffmpeg-build/README.txt")
        output.write(ROOT / "runtime/LICENSE", "ffmpeg-build/LICENSE")
        configuration = subprocess.check_output([str(ROOT / "runtime/ffmpeg.exe"), "-hide_banner", "-buildconf"],
                                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        output.writestr("ffmpeg-build/configuration.txt", configuration)
        for entry in entries:
            output.write(CACHE / entry["file"], "archives/" + entry["file"])
    collect_licenses(folder / "licenses", entries)
    for doc in ("README.md", "THIRD_PARTY.md", "CHANGELOG.md", "requirements.txt", "requirements-release.lock"):
        shutil.copy2(ROOT / doc, folder / doc)
    shutil.copytree(ROOT / "docs", folder / "docs", dirs_exist_ok=True)
    sources = folder / "source"
    sources.mkdir(exist_ok=True)
    shutil.copy2(source_zip, sources / source_zip.name)
    shutil.copy2(CACHE / "manifest.json", sources / "upstream-manifest.json")
    (sources / "commit.txt").write_text(commit + "\n", encoding="ascii")
    (folder / "SOURCE.txt").write_text(
        f"MediaLink Downloader {version}\nSource commit: {commit}\n"
        f"Project source: source/{source_zip.name}\n"
        f"Upstream source archives: {upstream_zip.name}\n"
        f"Download source attachment alongside this portable ZIP:\n"
        f"https://github.com/stelliakkk/medialink-downloader/releases/tag/v{version}\n"
        "License texts: licenses/ and runtime/LICENSE\n"
        "FFmpeg external-library versions: runtime/README.txt\n",
        encoding="utf-8")
    portable = ROOT / "dist" / f"{name}-win-x64.zip"
    pending = portable.with_suffix(".zip.part")
    try:
        with ZipFile(pending, "w", compression=ZIP_DEFLATED, compresslevel=1) as output:
            for path in sorted(folder.rglob("*")):
                relative = path.relative_to(folder)
                if relative.parts[0].lower() in {"data", "downloads", "reports"}:
                    continue
                if path.is_symlink() or path.is_junction():
                    raise ValueError("A release file is a filesystem link")
                if path.is_file():
                    if path.suffix.lower() in {".sqlite3", ".dat", ".log"} or path.name.lower() in {"settings.json", "app.lock"}:
                        raise ValueError(f"Private file in release: {relative}")
                    output.write(path, name + "/" + relative.as_posix())
        pending.replace(portable)
    finally:
        pending.unlink(missing_ok=True)
    assets = {portable.name: portable, "MediaLinkDownloader.exe": executable,
              source_zip.name: source_zip, upstream_zip.name: upstream_zip}
    checksums = ROOT / "dist/SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(path)}  {filename}\n" for filename, path in assets.items()), encoding="ascii")
    print(json.dumps({"commit": commit, "assets": [{"name": filename, "bytes": path.stat().st_size, "sha256": sha256(path)}
                                                   for filename, path in assets.items()], "checksums": str(checksums)}, indent=2))


if __name__ == "__main__":
    main()
