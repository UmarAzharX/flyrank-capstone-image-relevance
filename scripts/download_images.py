"""Download missing corpus files and verify known copies without overwriting them."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 25 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def photo_id(url: str, *, download: bool) -> str:
    if not isinstance(url, str):
        raise ValueError("Source URL must be text.")
    parts = urlsplit(url)
    host = "images.pexels.com" if download else "www.pexels.com"
    if parts.scheme != "https" or parts.netloc != host or parts.fragment:
        raise ValueError("Source URL must use the expected Pexels HTTPS host.")
    pattern = r"/photos/(\d+)/pexels-photo-\1\.jpeg" if download else r"/photo/[a-z0-9-]+-(\d+)/"
    match = re.fullmatch(pattern, parts.path)
    if not match:
        raise ValueError("Source URL must identify a Pexels photo.")
    return match.group(1)


def load_manifest(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Image manifest must be a nonempty list.")
    ids, names = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Image manifest entries must be objects.")
        identifier, name = row.get("id"), row.get("filename")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identifier):
            raise ValueError("Invalid image ID.")
        if (not isinstance(name, str) or len(name) > 255 or not name
                or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
                or name.endswith((".", " ")) or name.split(".")[0].upper() in RESERVED
                or Path(name).suffix.lower() not in {".jpg", ".jpeg"}):
            raise ValueError("Invalid corpus filename.")
        if identifier in ids or name.casefold() in names:
            raise ValueError("Duplicate image ID or filename.")
        ids.add(identifier)
        names.add(name.casefold())
        if row.get("source") != "pexels" or photo_id(row.get("source_page_url"), download=False) != photo_id(row.get("download_url"), download=True):
            raise ValueError("Source page and download must identify the same Pexels photo.")
        for prefix in ("download", "original"):
            digest, size = row.get(f"{prefix}_sha256"), row.get(f"{prefix}_size_bytes")
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ValueError("Missing or invalid SHA-256 checksum.")
            if type(size) is not int or not 0 < size <= MAX_BYTES:
                raise ValueError("Invalid image size.")
    return rows


def fingerprint(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected a regular image file.")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Image size is outside the supported range.")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("Image exceeds the size limit.")
            digest.update(chunk)
    return digest.hexdigest(), size


def verify_existing(path: Path, row: dict) -> str:
    found = fingerprint(path)
    for prefix in ("download", "original"):
        if found == (row[f"{prefix}_sha256"], row[f"{prefix}_size_bytes"]):
            return prefix
    raise ValueError("Existing file has an unknown checksum. It was not replaced.")


def download_one(row: dict, target: Path, *, opener=None) -> None:
    """Publish only a complete, verified file; fail if the destination appears."""
    if target.exists() or target.is_symlink():
        raise ValueError("Destination already exists. It was not replaced.")
    opener = opener or urlopen
    temp_path = None
    try:
        request = Request(row["download_url"], headers={"User-Agent": "FlyRank-Capstone-Corpus/1.0"})
        with opener(request, timeout=20) as response:
            if photo_id(response.geturl(), download=True) != photo_id(row["download_url"], download=True):
                raise ValueError("Download redirected to a different photo or host.")
            if response.headers.get_content_type() != "image/jpeg":
                raise ValueError("Download did not return a JPEG.")
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".corpus-", suffix=".part", delete=False) as stream:
                temp_path = Path(stream.name)
                digest, size, start = hashlib.sha256(), 0, b""
                while chunk := response.read(65536):
                    if not start:
                        start = chunk[:3]
                    size += len(chunk)
                    if size > MAX_BYTES or size > row["download_size_bytes"]:
                        raise ValueError("Download exceeds its recorded size.")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if start != b"\xff\xd8\xff" or (digest.hexdigest(), size) != (row["download_sha256"], row["download_size_bytes"]):
                raise ValueError("Downloaded file failed its size or checksum check.")
        # A hard link publishes the complete file and fails if target exists.
        os.link(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def acquire(rows: list[dict], folder: Path, *, verify_only=False, opener=None) -> list[dict]:
    if folder.is_symlink():
        raise ValueError("Image folder must not be a symbolic link.")
    folder = folder.resolve()
    if folder.exists() and not folder.is_dir():
        raise ValueError("Image folder must be a directory.")
    results = []
    # Check all existing files before sending requests or writing any images.
    for row in rows:
        target = folder / row["filename"]
        if target.is_symlink():
            raise ValueError(f"{row['id']}: image file must not be a symbolic link.")
        if target.exists():
            verify_existing(target, row)
        elif verify_only:
            raise ValueError(f"{row['id']}: image file is missing.")
    if not verify_only:
        folder.mkdir(parents=True, exist_ok=True)
    for row in rows:
        target = folder / row["filename"]
        if target.exists():
            variant = verify_existing(target, row)
            status = "verified_existing"
        else:
            download_one(row, target, opener=opener)
            variant = verify_existing(target, row)
            status = "downloaded"
        results.append({"id": row["id"], "status": status, "variant": variant})
        print(f"{row['id']}: {status} ({variant})", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Check local files without downloading.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/images")
    args = parser.parse_args()
    try:
        rows = load_manifest(PROJECT_ROOT / "data/images.json")
        results = acquire(rows, args.output_dir, verify_only=args.verify_only)
    except Exception as exc:
        # Avoid leaking unrelated paths or environment data in provider errors.
        print(f"Corpus check stopped ({type(exc).__name__}). Existing photos were not overwritten.")
        if isinstance(exc, ValueError):
            print(str(exc))
        return 1
    print(f"Corpus files verified: {len(results)}/{len(rows)}")
    print(f"New downloads: {sum(row['status'] == 'downloaded' for row in results)}")
    print("No database writes or Gemini requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
