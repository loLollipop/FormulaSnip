from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests

from formulasnip import __version__

LATEST_RELEASE_API = "https://api.github.com/repos/loLollipop/FormulaSnip/releases/latest"
LATEST_RELEASE_MANIFEST = (
    "https://github.com/loLollipop/FormulaSnip/releases/latest/download/"
    "FormulaSnip-update.json"
)
RELEASES_URL = "https://github.com/loLollipop/FormulaSnip/releases"
CHECK_INTERVAL_SECONDS = 12 * 60 * 60
REQUEST_TIMEOUT = (5.0, 30.0)
MAX_RELEASE_NOTES_LENGTH = 4_000
MAX_MANIFEST_BYTES = 64 * 1024
MAX_INSTALLER_BYTES = 4 * 1024 * 1024 * 1024
MAX_MANIFEST_REDIRECTS = 2
MAX_DOWNLOAD_REDIRECTS = 2
INSTALLER_ARGUMENTS = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/SP-",
    "/NORESTART",
    "/CLOSEAPPLICATIONS",
    "/NOFORCECLOSEAPPLICATIONS",
    "/NORESTARTAPPLICATIONS",
    "/AUTOUPDATE=1",
)

_TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_INSTALLER_PATTERN = re.compile(
    r"^FormulaSnip-v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
    r"-windows-x64-setup\.exe$"
)
_DIGEST_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_MANIFEST_DIGEST_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_TAGGED_MANIFEST_PATH_PATTERN = re.compile(
    r"^/loLollipop/FormulaSnip/releases/download/"
    r"(v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))/"
    r"FormulaSnip-update\.json$"
)
_REDIRECT_PATH_PATTERN = re.compile(
    r"^/github-production-release-asset/\d+/[^/]+$"
)
_INNO_APP_ID = "{2A0D2279-A23A-42B5-A431-045BC9778139}"
_UNINSTALL_REGISTRY_KEY = (
    rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{_INNO_APP_ID}_is1"
)


class UpdateError(RuntimeError):
    """A release response or downloaded installer failed a safety check."""


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class UpdateAsset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    asset: UpdateAsset

    @property
    def page_url(self) -> str:
        return f"{RELEASES_URL}/tag/{self.tag}"


def parse_version(value: str, *, tag: bool = False) -> tuple[int, int, int]:
    pattern = _TAG_PATTERN if tag else _VERSION_PATTERN
    match = pattern.fullmatch(value)
    if match is None:
        kind = "tag" if tag else "version"
        raise UpdateError(f"Invalid {kind}: {value!r}")
    try:
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]
    except ValueError as exc:
        kind = "tag" if tag else "version"
        raise UpdateError(f"Invalid {kind}: {value!r}") from exc


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def installer_name(version: str) -> str:
    parse_version(version)
    return f"FormulaSnip-v{version}-windows-x64-setup.exe"


def _asset_tag(asset: UpdateAsset) -> str:
    match = _INSTALLER_PATTERN.fullmatch(asset.name)
    if match is None:
        raise UpdateError("The installer filename is invalid.")
    version = match.group(1)
    parse_version(version)
    return f"v{version}"


def validate_asset_url(
    url: str,
    *,
    tag: str,
    name: str,
    allow_redirect: bool = False,
) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise UpdateError("The installer URL has an invalid port.") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port:
        raise UpdateError("The installer URL is not a trusted HTTPS GitHub asset URL.")
    if parsed.fragment:
        raise UpdateError("The installer URL contains an unexpected fragment.")

    expected_path = f"/loLollipop/FormulaSnip/releases/download/{tag}/{name}"
    if parsed.hostname == "github.com":
        if parsed.path != expected_path or parsed.query:
            raise UpdateError("The installer URL does not match this FormulaSnip release.")
        return
    if (
        allow_redirect
        and parsed.hostname == "release-assets.githubusercontent.com"
        and _REDIRECT_PATH_PATTERN.fullmatch(parsed.path)
    ):
        return
    raise UpdateError("The installer URL host is not an allowed GitHub release host.")


def parse_release(payload: object, current_version: str = __version__) -> ReleaseInfo | None:
    if not isinstance(payload, Mapping):
        raise UpdateError("GitHub returned an invalid release document.")
    if payload.get("draft") is not False or payload.get("prerelease") is not False:
        return None

    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("The release tag is missing.")
    version_tuple = parse_version(tag, tag=True)
    version = tag[1:]
    if version_tuple <= parse_version(current_version):
        return None

    expected_name = installer_name(version)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The release asset list is missing.")
    matches = [
        asset
        for asset in assets
        if isinstance(asset, Mapping) and asset.get("name") == expected_name
    ]
    if len(matches) != 1:
        raise UpdateError(f"The release must contain exactly one {expected_name} asset.")
    raw_asset = matches[0]

    url = raw_asset.get("browser_download_url")
    size = raw_asset.get("size")
    digest = raw_asset.get("digest")
    if not isinstance(url, str):
        raise UpdateError("The installer download URL is missing.")
    validate_asset_url(url, tag=tag, name=expected_name)
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise UpdateError("The installer size is missing or invalid.")
    if not isinstance(digest, str) or (digest_match := _DIGEST_PATTERN.fullmatch(digest)) is None:
        raise UpdateError("The installer does not have a valid GitHub SHA-256 digest.")

    body = payload.get("body", "")
    notes = body if isinstance(body, str) else ""
    notes = notes[:MAX_RELEASE_NOTES_LENGTH]
    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=notes,
        asset=UpdateAsset(expected_name, url, size, digest_match.group(1).lower()),
    )


def _validate_manifest_url(url: str, *, stage: str) -> str | None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UpdateError("The update manifest URL has an invalid port.") from exc
    if parsed.scheme != "https" or parsed.username or parsed.password or port:
        raise UpdateError("The update manifest URL is not a trusted HTTPS URL.")
    if parsed.fragment:
        raise UpdateError("The update manifest URL contains an unexpected fragment.")

    if stage == "latest":
        expected = urlsplit(LATEST_RELEASE_MANIFEST)
        if parsed.hostname != "github.com" or parsed.path != expected.path or parsed.query:
            raise UpdateError("The update manifest latest URL is invalid.")
        return None
    if stage == "tagged":
        if parsed.hostname != "github.com" or parsed.query:
            raise UpdateError("The update manifest did not resolve to a tagged release.")
        match = _TAGGED_MANIFEST_PATH_PATTERN.fullmatch(parsed.path)
        if match is None:
            raise UpdateError("The update manifest did not resolve to a tagged release.")
        return match.group(1)
    if stage == "asset":
        if (
            parsed.hostname != "release-assets.githubusercontent.com"
            or _REDIRECT_PATH_PATTERN.fullmatch(parsed.path) is None
        ):
            raise UpdateError("The update manifest redirect host is not trusted.")
        return None
    raise UpdateError("The update manifest redirect state is invalid.")


def _read_manifest_response(response: Any) -> object:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError) as exc:
            raise UpdateError("The update manifest has an invalid Content-Length.") from exc
        if declared_size < 0 or declared_size > MAX_MANIFEST_BYTES:
            raise UpdateError("The update manifest is too large.")

    content = bytearray()
    for chunk in response.iter_content(chunk_size=16 * 1024):
        if not chunk:
            continue
        if len(content) + len(chunk) > MAX_MANIFEST_BYTES:
            raise UpdateError("The update manifest is too large.")
        content.extend(chunk)
    try:
        return json.loads(bytes(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The update manifest is not valid JSON.") from exc


def parse_manifest(
    payload: object,
    *,
    resolved_tag: str,
    current_version: str = __version__,
) -> ReleaseInfo | None:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "version",
        "tag",
        "notes",
        "asset",
    }:
        raise UpdateError("The update manifest has an invalid schema.")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise UpdateError("The update manifest schema version is unsupported.")

    version = payload.get("version")
    tag = payload.get("tag")
    notes = payload.get("notes")
    if not isinstance(version, str) or not isinstance(tag, str):
        raise UpdateError("The update manifest version or tag is missing.")
    version_tuple = parse_version(version)
    parse_version(tag, tag=True)
    if tag != f"v{version}" or tag != resolved_tag:
        raise UpdateError("The update manifest tag does not match the resolved release.")
    if not isinstance(notes, str):
        raise UpdateError("The update manifest release notes are invalid.")

    asset = payload.get("asset")
    if not isinstance(asset, Mapping) or set(asset) != {"name", "size", "sha256"}:
        raise UpdateError("The update manifest asset has an invalid schema.")
    expected_name = installer_name(version)
    name = asset.get("name")
    size = asset.get("size")
    sha256 = asset.get("sha256")
    if name != expected_name:
        raise UpdateError("The update manifest installer filename is invalid.")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise UpdateError("The update manifest installer size is invalid.")
    if not isinstance(sha256, str) or _MANIFEST_DIGEST_PATTERN.fullmatch(sha256) is None:
        raise UpdateError("The update manifest installer SHA-256 is invalid.")
    if version_tuple <= parse_version(current_version):
        return None

    url = f"{RELEASES_URL}/download/{tag}/{expected_name}"
    validate_asset_url(url, tag=tag, name=expected_name)
    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=notes[:MAX_RELEASE_NOTES_LENGTH],
        asset=UpdateAsset(expected_name, url, size, sha256.lower()),
    )


def _fetch_release_manifest(
    current_version: str,
    *,
    client: HttpClient,
) -> ReleaseInfo | None:
    current_url = LATEST_RELEASE_MANIFEST
    resolved_tag: str | None = None
    stages = ("latest", "tagged", "asset")
    for redirect_count in range(MAX_MANIFEST_REDIRECTS + 1):
        response: Any = None
        try:
            stage = stages[redirect_count]
            _validate_manifest_url(current_url, stage=stage)
            response = client.get(
                current_url,
                headers={"Accept": "application/json", "User-Agent": "FormulaSnip-Updater"},
                timeout=REQUEST_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
            response_url = str(getattr(response, "url", current_url) or current_url)
            response_tag = _validate_manifest_url(response_url, stage=stage)
            if response_tag is not None:
                resolved_tag = response_tag
            status_code = int(getattr(response, "status_code", 0))
            if 300 <= status_code < 400:
                location = response.headers.get("Location")
                if not isinstance(location, str) or not location:
                    raise UpdateError("The update manifest redirect is missing its destination.")
                if redirect_count >= MAX_MANIFEST_REDIRECTS:
                    raise UpdateError("The update manifest used too many redirects.")
                try:
                    next_url = urljoin(current_url, location)
                except ValueError as exc:
                    raise UpdateError(
                        "The update manifest redirect URL is invalid."
                    ) from exc
                next_tag = _validate_manifest_url(next_url, stage=stages[redirect_count + 1])
                if next_tag is not None:
                    resolved_tag = next_tag
                response.close()
                current_url = next_url
                continue
            response.raise_for_status()
            if stage != "asset" or resolved_tag is None:
                raise UpdateError("The update manifest did not follow the expected redirects.")
            payload = _read_manifest_response(response)
            return parse_manifest(
                payload,
                resolved_tag=resolved_tag,
                current_version=current_version,
            )
        except requests.RequestException as exc:
            raise UpdateError("Unable to download the update manifest.") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
    raise UpdateError("The update manifest used too many redirects.")


def _fetch_release_api(
    current_version: str,
    *,
    client: HttpClient,
) -> ReleaseInfo | None:
    response: Any = None
    try:
        response = client.get(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "FormulaSnip-Updater"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        status_code = int(getattr(response, "status_code", 0))
        if 300 <= status_code < 400:
            raise UpdateError("GitHub returned an unexpected redirect for the release API.")
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpdateError("Unable to check the GitHub release API.") from exc
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
    return parse_release(payload, current_version)


def fetch_latest_release(
    current_version: str = __version__,
    *,
    client: HttpClient = requests,
) -> ReleaseInfo | None:
    try:
        return _fetch_release_manifest(current_version, client=client)
    except UpdateError:
        try:
            return _fetch_release_api(current_version, client=client)
        except UpdateError as api_error:
            raise UpdateError(
                "无法检查更新：静态更新清单和 GitHub API 均不可用，请稍后重试。"
            ) from api_error


def should_check_for_updates(
    last_check_seconds: object,
    *,
    now_seconds: int,
    manual: bool = False,
    interval_seconds: int = CHECK_INTERVAL_SECONDS,
) -> bool:
    if manual:
        return True
    try:
        last_check = int(last_check_seconds)
    except (TypeError, ValueError, OverflowError):
        return True
    return (
        last_check < 0
        or now_seconds - last_check >= interval_seconds
        or now_seconds < last_check
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installer(path: Path, asset: UpdateAsset) -> None:
    if path.name != asset.name or not path.is_file():
        raise UpdateError("The cached installer path is invalid.")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise UpdateError("The cached installer cannot be inspected.") from exc
    if size != asset.size:
        raise UpdateError("The installer size does not match the GitHub release metadata.")
    if _sha256_file(path) != asset.sha256:
        raise UpdateError("The installer SHA-256 digest does not match GitHub metadata.")


def _registered_install_directory() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _UNINSTALL_REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "InstallLocation")
    except (ImportError, OSError):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def is_installed_build() -> bool:
    """Return whether this frozen executable is the registered Inno install."""
    if sys.platform != "win32" or not bool(getattr(sys, "frozen", False)):
        return False
    install_directory = _registered_install_directory()
    if install_directory is None:
        return False
    try:
        executable = Path(sys.executable).resolve()
        registered_executable = (install_directory / "FormulaSnip.exe").resolve()
    except OSError:
        return False
    return executable == registered_executable


def launch_verified_installer(
    path: Path,
    asset: UpdateAsset,
    *,
    start_detached: Callable[[str, list[str]], object],
) -> bool:
    """Revalidate a cached Setup and launch it with fixed, local arguments."""
    verify_installer(path, asset)
    result = start_detached(str(path), list(INSTALLER_ARGUMENTS))
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


def _open_trusted_download(
    asset: UpdateAsset,
    *,
    tag: str,
    client: HttpClient,
) -> Any:
    current_url = asset.url
    for redirect_count in range(MAX_DOWNLOAD_REDIRECTS + 1):
        response: Any = None
        try:
            response = client.get(
                current_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "FormulaSnip-Updater",
                },
                timeout=REQUEST_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
            status_code = int(getattr(response, "status_code", 0))
            response_url = str(getattr(response, "url", current_url) or current_url)
            validate_asset_url(
                response_url,
                tag=tag,
                name=asset.name,
                allow_redirect=redirect_count > 0,
            )
            if 300 <= status_code < 400:
                location = response.headers.get("Location")
                if not isinstance(location, str) or not location:
                    raise UpdateError("The installer redirect is missing its destination.")
                if redirect_count >= MAX_DOWNLOAD_REDIRECTS:
                    raise UpdateError("The installer download used too many redirects.")
                next_url = urljoin(current_url, location)
                validate_asset_url(
                    next_url,
                    tag=tag,
                    name=asset.name,
                    allow_redirect=True,
                )
                response.close()
                current_url = next_url
                continue
            response.raise_for_status()
            return response
        except Exception:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
            raise
    raise UpdateError("The installer download used too many redirects.")


def download_installer(
    asset: UpdateAsset,
    cache_directory: Path,
    *,
    client: HttpClient = requests,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    tag = _asset_tag(asset)
    validate_asset_url(asset.url, tag=tag, name=asset.name)
    cache_directory.mkdir(parents=True, exist_ok=True)
    destination = cache_directory / asset.name
    partial = cache_directory / (
        f".{asset.name}.{os.getpid()}.{uuid4().hex}.part"
    )
    if destination.is_file():
        try:
            verify_installer(destination, asset)
            if progress is not None:
                progress(asset.size, asset.size)
            return destination
        except UpdateError:
            destination.unlink(missing_ok=True)
    response: Any = None
    downloaded = 0
    digest = hashlib.sha256()
    try:
        response = _open_trusted_download(asset, tag=tag, client=client)
        final_url = str(getattr(response, "url", asset.url))
        validate_asset_url(final_url, tag=tag, name=asset.name, allow_redirect=True)
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                response_size = int(content_length)
            except ValueError as exc:
                raise UpdateError("The installer response has an invalid size.") from exc
            if response_size != asset.size:
                raise UpdateError("The installer response size does not match GitHub metadata.")

        with partial.open("xb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > asset.size:
                    raise UpdateError("The installer is larger than its GitHub metadata.")
                digest.update(chunk)
                handle.write(chunk)
                if progress is not None:
                    progress(downloaded, asset.size)
        if downloaded != asset.size:
            raise UpdateError("The installer download is incomplete.")
        if digest.hexdigest() != asset.sha256:
            raise UpdateError("The installer SHA-256 digest does not match GitHub metadata.")
        os.replace(partial, destination)
        verify_installer(destination, asset)
        return destination
    except requests.RequestException as exc:
        raise UpdateError("Unable to download the installer.") from exc
    except OSError as exc:
        raise UpdateError("Unable to save the installer in the user cache.") from exc
    finally:
        partial.unlink(missing_ok=True)
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
