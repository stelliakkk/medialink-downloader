"""Collect versioned upstream sources without modifying the Python environment."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache/release-sources"
QT = "https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules"
PYSIDE = "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src"


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def open_url(url):
    for attempt in range(3):
        try:
            return urlopen(Request(url, headers={"User-Agent": "MediaLink-source-release/3.0.6"}), timeout=45)
        except URLError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def download(name, url, expected=None):
    target = CACHE / name
    if target.is_file() and (expected is None or sha256(target) == expected):
        return {"file": name, "url": url, "sha256": sha256(target), "bytes": target.stat().st_size}
    pending = target.with_suffix(target.suffix + ".part")
    try:
        with open_url(url) as response, pending.open("wb") as out:
            shutil.copyfileobj(response, out)
        actual = sha256(pending)
        if expected is not None and actual != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
        with tarfile.open(pending):
            pass
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return {"file": name, "url": url, "sha256": actual, "bytes": target.stat().st_size}


def pypi_source(name, version):
    normalized = re.sub(r"[-_.]+", "-", name.lower())
    proven = []
    for provenance in (CACHE / "cache-provenance.json", CACHE / "manifest.json"):
        if provenance.is_file():
            proven.extend(json.loads(provenance.read_text("utf-8")))
    for entry in proven:
        for suffix in (".tar.gz", ".tar.xz"):
            tail = f"-{version}{suffix}"
            if entry["file"].endswith(tail) and re.sub(r"[-_.]+", "-", entry["file"][:-len(tail)].lower()) == normalized:
                path = CACHE / entry["file"]
                if path.is_file() and sha256(path) == entry["sha256"]:
                    return download(entry["file"], entry["url"], entry["sha256"])
    with open_url(f"https://pypi.org/pypi/{name}/{version}/json") as response:
        data = json.load(response)
    entry = next(x for x in data["urls"] if x["packagetype"] == "sdist")
    return download(entry["filename"], entry["url"], entry["digests"]["sha256"])


def qt_source(name, base):
    target = CACHE / name
    if target.is_file():
        return download(name, f"{base}/{name}")
    with open_url(f"{base}/{name}.sha256") as response:
        expected = response.read(8192).decode("ascii").split()[0]
    if not re.fullmatch("[a-fA-F0-9]{64}", expected):
        raise ValueError("Invalid upstream checksum")
    return download(name, f"{base}/{name}", expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-cache", type=Path)
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    if args.reuse_cache:
        manifest = json.loads((args.reuse_cache / "manifest.json").read_text("utf-8"))
        for entry in manifest:
            source = args.reuse_cache / entry["file"]
            if source.is_file() and sha256(source) == entry["sha256"] and not (CACHE / source.name).exists():
                shutil.copy2(source, CACHE / source.name)
        (CACHE / "cache-provenance.json").write_text(json.dumps(manifest), encoding="utf-8")
    packages = [line.split("==", 1) for line in (ROOT / "requirements-release.lock").read_text("ascii").splitlines() if line]
    extra = [
        ("Python-3.14.5.tar.xz", "https://www.python.org/ftp/python/3.14.5/Python-3.14.5.tar.xz"),
        ("openssl-3.0.20.tar.gz", "https://codeload.github.com/openssl/openssl/tar.gz/refs/tags/openssl-3.0.20"),
        ("ffmpeg-946fcce07b.tar.gz", "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/946fcce07b"),
        ("gyan-codexffmpeg-9.0.2.tar.gz", "https://codeload.github.com/GyanD/codexffmpeg/tar.gz/refs/tags/9.0.2"),
        ("x264-0480cb0.tar.gz", "https://codeload.github.com/mirror/x264/tar.gz/0480cb0"),
        ("x265-116b875.tar.gz", "https://codeload.github.com/Multicorewareinc/x265/tar.gz/116b875"),
        ("rubberband-v4.0.0.tar.gz", "https://codeload.github.com/breakfastquay/rubberband/tar.gz/refs/tags/v4.0.0"),
        ("vidstab-e2445c4.tar.gz", "https://codeload.github.com/georgmartius/vid.stab/tar.gz/e2445c4"),
    ]
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(pypi_source, name, version): f"{name}=={version}" for name, version in packages
                if name.lower() not in ("pyside6-essentials", "shiboken6")}
        for name, base in [("qtbase-everywhere-src-6.12.0.tar.xz", QT), ("qtsvg-everywhere-src-6.12.0.tar.xz", QT),
                           ("pyside-setup-everywhere-src-6.12.0.tar.xz", PYSIDE)]:
            jobs[pool.submit(qt_source, name, base)] = name
        for name, url in extra:
            jobs[pool.submit(download, name, url)] = name
        for job in as_completed(jobs):
            try:
                rows.append(job.result())
                print("Ready:", jobs[job], flush=True)
            except Exception as error:
                failures.append({"source": jobs[job], "error": type(error).__name__})
                print("Failed:", jobs[job], type(error).__name__, flush=True)
    (CACHE / "manifest.json").write_text(json.dumps(sorted(rows, key=lambda x: x["file"]), indent=2) + "\n", encoding="utf-8")
    if failures:
        (CACHE / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
        raise SystemExit(f"{len(failures)} source downloads failed; successful results cached.")
    (CACHE / "failures.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
