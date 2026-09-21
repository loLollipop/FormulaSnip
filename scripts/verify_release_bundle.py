"""Read-only fail-closed hygiene gate for a fresh frozen directory or release ZIP.

This gate does not certify version, licenses, signatures or runtime correctness.
Run it alongside frozen smoke tests; an old bundle is not a release candidate.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


def forbidden_name(name: str) -> bool:
    normalized = name.replace("\\", "/").lower()
    parts = PurePosixPath(normalized).parts
    return any(part in {"__pycache__", ".git", ".env", "direct_url.json"}
               or part.startswith(".env.") for part in parts) or (
        normalized.endswith((".pyc", ".debug.pak"))
        or parts[-1] == "v8_context_snapshot.debug.bin"
        or ("qmltooling" in parts and normalized.endswith(".dll"))
        or ("qtwebengine" in normalized and "devtools" in normalized
            and "debug" in normalized)
    )


def _has_build_path(stream: BinaryIO, project_root: Path) -> bool:
    root = str(project_root.resolve())
    variants = {root, root.replace("\\", "/"), root.replace("\\", "\\\\"),
                project_root.resolve().as_uri()}
    markers = tuple(value.lower().encode(encoding).lower()
                    for value in variants for encoding in ("utf-8", "utf-16-le"))
    tail = b""
    while chunk := stream.read(1024 * 1024):
        data = (tail + chunk).lower()
        if any(marker in data for marker in markers):
            return True
        if re.search(rb"file:///[a-z]:[/\\]", data):
            return True
        tail = data[-max(2048, *(len(marker) for marker in markers)):]
    return False


def verify_bundle(target: Path, project_root: Path) -> list[str]:
    issues: list[str] = []
    count = 0

    def scan(name: str, stream: BinaryIO) -> None:
        nonlocal count
        count += 1
        if forbidden_name(name):
            issues.append(f"Forbidden resource: {name}")
        if _has_build_path(stream, project_root):
            issues.append(f"Local build path: {name}")

    try:
        if target.is_dir():
            for path in target.rglob("*"):
                if path.is_symlink():
                    issues.append(f"Unexpected symlink: {path.name}")
                elif path.is_dir() and forbidden_name(path.relative_to(target).as_posix()):
                    issues.append(f"Forbidden directory: {path.relative_to(target).as_posix()}")
                elif path.is_file():
                    with path.open("rb") as stream:
                        scan(path.relative_to(target).as_posix(), stream)
        elif target.is_file() and zipfile.is_zipfile(target):
            with zipfile.ZipFile(target) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if ".." in PurePosixPath(info.filename).parts:
                        issues.append("Unsafe archive member")
                    with archive.open(info) as stream:
                        scan(info.filename, stream)
        else:
            issues.append("Expected a frozen application directory or ZIP")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        issues.append("Unable to read the complete bundle")
    if count == 0:
        issues.append("Empty or unreadable bundle")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    issues = verify_bundle(args.bundle, args.project_root)
    for issue in issues:
        print(issue, file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
