from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


class ModelBundleError(RuntimeError):
    """The pinned MathCraft model bundle is unavailable or invalid."""


def _validate_portable_relative_path(
    value: object,
    *,
    label: str,
    allow_subdirectories: bool = True,
) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ModelBundleError(f"{label} is not a portable relative path: {value!r}")
    parts = value.split("/")
    if (
        any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or ":" in value
        or (not allow_subdirectories and len(parts) != 1)
    ):
        raise ModelBundleError(f"{label} is not a portable relative path: {value!r}")
    return value


def _validate_archive_member(name: str) -> str:
    normalized = name[:-1] if name.endswith("/") else name
    return _validate_portable_relative_path(
        normalized,
        label="Model archive member",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_model_lock(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelBundleError(f"Unable to read model lock: {path}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ModelBundleError("Unsupported model lock schema.")
    required_strings = (
        "model_id",
        "model_version",
        "source_url",
        "archive_sha256",
        "license",
    )
    if any(not isinstance(document.get(key), str) or not document[key] for key in required_strings):
        raise ModelBundleError("Model lock metadata is incomplete.")
    _validate_portable_relative_path(
        document["model_id"],
        label="Model id",
        allow_subdirectories=False,
    )
    source = urlsplit(document["source_url"])
    if source.scheme != "https" or source.hostname != "github.com":
        raise ModelBundleError("Model source must be a pinned GitHub HTTPS asset.")
    if (
        not isinstance(document.get("archive_size"), int)
        or document["archive_size"] <= 0
        or document["archive_size"] > MAX_ARCHIVE_BYTES
    ):
        raise ModelBundleError("Model archive size is invalid.")
    files = document.get("files")
    if not isinstance(files, list) or not files:
        raise ModelBundleError("Model lock contains no files.")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise ModelBundleError("Model file entry is invalid.")
        relative = _validate_portable_relative_path(
            item.get("path"),
            label="Model file path",
        )
        if relative in seen:
            raise ModelBundleError("Model file path is invalid or duplicated.")
        seen.add(relative)
        if not isinstance(item.get("size"), int) or item["size"] < 0:
            raise ModelBundleError(f"Model file size is invalid: {relative}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ModelBundleError(f"Model file hash is invalid: {relative}")
    return document


def verify_model_directory(destination: Path, lock: dict[str, Any]) -> None:
    if not destination.is_dir():
        raise ModelBundleError(f"Bundled model directory is missing: {destination}")
    expected = {str(item["path"]): item for item in lock["files"]}
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        raise ModelBundleError(
            f"Bundled model file set differs; missing={missing}, extra={extra}"
        )
    for relative, item in expected.items():
        file_path = destination / relative
        if file_path.stat().st_size != item["size"]:
            raise ModelBundleError(f"Bundled model size mismatch: {relative}")
        if sha256_file(file_path).casefold() != str(item["sha256"]).casefold():
            raise ModelBundleError(f"Bundled model hash mismatch: {relative}")


def _download_archive(lock: dict[str, Any], archive_path: Path) -> None:
    request = urllib.request.Request(
        str(lock["source_url"]),
        headers={"User-Agent": "FormulaSnip-release-builder"},
    )
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, archive_path.open(
            "wb"
        ) as output:
            final_url = urlsplit(response.geturl())
            if (
                final_url.scheme != "https"
                or final_url.hostname not in ALLOWED_DOWNLOAD_HOSTS
            ):
                raise ModelBundleError("Model download redirected to an untrusted host.")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ModelBundleError("Model archive exceeds the release limit.")
                output.write(chunk)
                digest.update(chunk)
    except ModelBundleError:
        raise
    except OSError as exc:
        raise ModelBundleError("Unable to download the pinned MathCraft model.") from exc
    if total != lock["archive_size"]:
        raise ModelBundleError("Model archive size does not match the lock file.")
    if digest.hexdigest().casefold() != str(lock["archive_sha256"]).casefold():
        raise ModelBundleError("Model archive hash does not match the lock file.")


def _extract_expected_files(
    archive_path: Path,
    destination: Path,
    lock: dict[str, Any],
) -> None:
    model_id = str(lock["model_id"])
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members: dict[str, zipfile.ZipInfo] = {}
            for item in archive.infolist():
                member_name = _validate_archive_member(item.filename)
                if member_name in members:
                    raise ModelBundleError(
                        f"Model archive contains a duplicate entry: {member_name}"
                    )
                members[member_name] = item
            for file_spec in lock["files"]:
                relative = str(file_spec["path"])
                candidates = (relative, f"{model_id}/{relative}")
                matches = [members[name] for name in candidates if name in members]
                if len(matches) != 1 or matches[0].is_dir():
                    raise ModelBundleError(f"Model archive entry is missing: {relative}")
                expected_size = int(file_spec["size"])
                if matches[0].file_size != expected_size:
                    raise ModelBundleError(
                        f"Model archive entry size mismatch: {relative}"
                    )
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(matches[0]) as source, target.open("wb") as output:
                    remaining = expected_size
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ModelBundleError(
                                f"Model archive entry ended early: {relative}"
                            )
                        output.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise ModelBundleError(
                            f"Model archive entry exceeds locked size: {relative}"
                        )
    except ModelBundleError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ModelBundleError("Unable to extract the pinned MathCraft model.") from exc


def _validated_staging_root(destination: Path) -> tuple[Path, Path]:
    project_root = Path(__file__).resolve().parents[1]
    allowed_root = (project_root / "build" / "bundled-models").resolve()
    resolved = destination.resolve()
    if resolved != allowed_root and allowed_root not in resolved.parents:
        raise ModelBundleError(
            f"Bundle destination must stay below {allowed_root}: {resolved}"
        )
    return allowed_root, resolved


def prepare_model_bundle(
    destination: Path,
    lock: dict[str, Any],
) -> str:
    allowed_root, resolved_destination = _validated_staging_root(destination)
    try:
        verify_model_directory(resolved_destination, lock)
        return "reused"
    except ModelBundleError:
        pass

    allowed_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-stage-", dir=allowed_root) as temp_name:
        temporary_root = Path(temp_name)
        archive_path = temporary_root / "model.zip"
        extracted = temporary_root / str(lock["model_id"])
        extracted.mkdir()
        _download_archive(lock, archive_path)
        _extract_expected_files(archive_path, extracted, lock)
        verify_model_directory(extracted, lock)
        if resolved_destination.exists():
            shutil.rmtree(resolved_destination)
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted), str(resolved_destination))
    verify_model_directory(resolved_destination, lock)
    return "downloaded"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the pinned MathCraft model bundle.")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    try:
        lock = load_model_lock(arguments.lock)
        if arguments.verify_only:
            verify_model_directory(arguments.destination, lock)
            outcome = "verified"
        else:
            outcome = prepare_model_bundle(arguments.destination, lock)
    except ModelBundleError as exc:
        parser.exit(1, f"Model bundle error: {exc}\n")
    print(f"MathCraft model bundle {outcome}: {arguments.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
