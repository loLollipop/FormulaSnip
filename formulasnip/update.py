from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
from collections.abc import Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import requests
from requests.auth import AuthBase
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from formulasnip import __version__

LATEST_RELEASE_API = "https://api.github.com/repos/loLollipop/FormulaSnip/releases/latest"
LATEST_RELEASE_MANIFEST = (
    "https://github.com/loLollipop/FormulaSnip/releases/latest/download/"
    "FormulaSnip-update-v2.json"
)
LEGACY_RELEASE_MANIFEST = (
    "https://github.com/loLollipop/FormulaSnip/releases/latest/download/"
    "FormulaSnip-update.json"
)
RELEASES_URL = "https://github.com/loLollipop/FormulaSnip/releases"
CHECK_INTERVAL_SECONDS = 12 * 60 * 60
REQUEST_TIMEOUT = (5.0, 30.0)
MAX_RELEASE_NOTES_LENGTH = 4_000
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RELEASE_API_BYTES = 256 * 1024
UPDATE_CHECK_TIMEOUT_SECONDS = 45.0
_CHECK_TRANSPORT_SLOTS = BoundedSemaphore(2)
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
    r"-windows-x64-(?:setup|update)\.exe$"
)
_DIGEST_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_MANIFEST_DIGEST_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_MANIFEST_NAMES = {
    1: "FormulaSnip-update.json",
    2: "FormulaSnip-update-v2.json",
}
_REDIRECT_PATH_PATTERN = re.compile(
    r"^/github-production-release-asset/\d+/[^/]+$"
)
_INNO_APP_ID = "{2A0D2279-A23A-42B5-A431-045BC9778139}"
_UNINSTALL_REGISTRY_KEY = (
    rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{_INNO_APP_ID}_is1"
)


class UpdateError(RuntimeError):
    """A release response or downloaded installer failed a safety check."""


class UpdateCancelled(UpdateError):
    """The caller cancelled an in-flight update operation."""


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


class UpdateCancellation:
    """Thread-safe cancellation signal that can also abort active transports."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._abort_callbacks: set[Callable[[], None]] = set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            self._event.set()
            callbacks = tuple(self._abort_callbacks)
        for callback in callbacks:
            with suppress(Exception):
                callback()

    def add_abort_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._event.is_set():
                abort_now = True
            else:
                self._abort_callbacks.add(callback)
                abort_now = False
        if abort_now:
            with suppress(Exception):
                callback()

        def remove() -> None:
            with self._lock:
                self._abort_callbacks.discard(callback)

        return remove

    def run_if_active(self, callback: Callable[[], None]) -> bool:
        """Run one short publication step unless cancellation already won."""
        with self._lock:
            if self._event.is_set():
                return False
            callback()
            return True


class _AnonymousAuth(AuthBase):
    """Explicitly disable netrc credentials without disabling proxy/CA settings."""

    def __call__(self, request: Any) -> Any:
        request.headers.pop("Authorization", None)
        return request


class _ExplicitAuthClient:
    """Apply explicit anonymous auth without mutating a caller-owned Session."""

    def __init__(self, client: HttpClient) -> None:
        self._client = client
        self._auth = _AnonymousAuth()

    def get(self, url: str, **kwargs: Any) -> Any:
        kwargs["auth"] = self._auth
        return self._client.get(url, **kwargs)


class _ConnectionTracker:
    """Own duplicate socket handles that can interrupt a requests Session."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._sockets: list[Any] = []
        self._aborted = False

    def track(self, connection_socket: Any) -> None:
        with self._lock:
            if self._aborted:
                abort_now = True
            else:
                self._sockets.append(connection_socket)
                abort_now = False
        if abort_now:
            self._abort_socket(connection_socket)

    def abort(self) -> None:
        with self._lock:
            self._aborted = True
            sockets = tuple(self._sockets)
        for connection_socket in sockets:
            self._abort_socket(connection_socket)

    def close(self) -> None:
        with self._lock:
            sockets = tuple(self._sockets)
            self._sockets.clear()
        for connection_socket in sockets:
            with suppress(OSError):
                connection_socket.close()

    @staticmethod
    def _abort_socket(connection_socket: Any) -> None:
        with suppress(OSError):
            connection_socket.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            connection_socket.close()


def _tracked_pool_classes(
    tracker: _ConnectionTracker,
) -> tuple[type[HTTPConnectionPool], type[HTTPSConnectionPool]]:
    class TrackedHTTPConnection(HTTPConnection):
        def _new_conn(self) -> Any:
            connection_socket = super()._new_conn()
            tracker.track(connection_socket.dup())
            return connection_socket

    class TrackedHTTPSConnection(HTTPSConnection):
        def _new_conn(self) -> Any:
            connection_socket = super()._new_conn()
            # TLS wrapping detaches the original handle. The duplicate can still
            # interrupt the same TCP connection while waiting for headers/body.
            tracker.track(connection_socket.dup())
            return connection_socket

    class TrackedHTTPConnectionPool(HTTPConnectionPool):
        ConnectionCls = TrackedHTTPConnection

    class TrackedHTTPSConnectionPool(HTTPSConnectionPool):
        ConnectionCls = TrackedHTTPSConnection

    return TrackedHTTPConnectionPool, TrackedHTTPSConnectionPool


class _CancellableHTTPAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, tracker: _ConnectionTracker) -> None:
        http_pool, https_pool = _tracked_pool_classes(tracker)
        self._tracked_pools = {"http": http_pool, "https": https_pool}
        super().__init__()

    def _configure_pool_manager(self, manager: Any) -> None:
        manager.pool_classes_by_scheme = self._tracked_pools.copy()

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        self._configure_pool_manager(self.poolmanager)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        if not proxy.casefold().startswith("socks"):
            self._configure_pool_manager(manager)
        return manager


@contextmanager
def _request_client(
    client: HttpClient,
    cancel_event: CancellationSignal | None,
) -> Any:
    if client is not requests:
        if isinstance(client, requests.Session):
            yield _ExplicitAuthClient(client)
        else:
            yield client
        return
    tracker = _ConnectionTracker()
    session = requests.Session()
    session.auth = _AnonymousAuth()
    adapter = _CancellableHTTPAdapter(tracker)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    remove_abort: Callable[[], None] | None = None
    remove_close: Callable[[], None] | None = None
    add_abort = getattr(cancel_event, "add_abort_callback", None)
    if callable(add_abort):
        remove_abort = add_abort(tracker.abort)
        remove_close = add_abort(session.close)
    try:
        yield session
    finally:
        if remove_abort is not None:
            remove_abort()
        if remove_close is not None:
            remove_close()
        session.close()
        tracker.close()


def _raise_if_cancelled(cancel_event: CancellationSignal | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled("Update operation cancelled.")


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
    fallback_asset: UpdateAsset | None = None

    @property
    def page_url(self) -> str:
        return f"{RELEASES_URL}/tag/{self.tag}"

    @property
    def is_lightweight_update(self) -> bool:
        return self.asset.name.endswith("-windows-x64-update.exe")


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


def installer_name(version: str, *, lightweight: bool = False) -> str:
    parse_version(version)
    package_kind = "update" if lightweight else "setup"
    return f"FormulaSnip-v{version}-windows-x64-{package_kind}.exe"


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


def installed_model_bundle_identity(
    *,
    lock_path: Path | None = None,
    bundled_root: Path | None = None,
) -> str | None:
    """Return the installed model-lock digest after full model SHA-256 verification."""

    if lock_path is None or bundled_root is None:
        frozen_root = getattr(sys, "_MEIPASS", None)
        if not frozen_root:
            return None
        frozen_path = Path(frozen_root)
        lock_path = lock_path or frozen_path / "MODEL_ASSETS.json"
        bundled_root = bundled_root or frozen_path / "MathCraft" / "models"
    try:
        from formulasnip.recognition.mathcraft_backend import (
            _verify_bundled_model_root,
        )

        lock_bytes = lock_path.read_bytes()
        if _verify_bundled_model_root(bundled_root, lock_path) is not None:
            return None
        if lock_path.read_bytes() != lock_bytes:
            return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return hashlib.sha256(lock_bytes).hexdigest()


def _parse_manifest_asset(
    payload: object,
    *,
    version: str,
    tag: str,
    lightweight: bool,
) -> UpdateAsset:
    if not isinstance(payload, Mapping) or set(payload) != {"name", "size", "sha256"}:
        raise UpdateError("The update manifest asset has an invalid schema.")
    expected_name = installer_name(version, lightweight=lightweight)
    name = payload.get("name")
    size = payload.get("size")
    sha256 = payload.get("sha256")
    if name != expected_name:
        raise UpdateError("The update manifest installer filename is invalid.")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise UpdateError("The update manifest installer size is invalid.")
    if not isinstance(sha256, str) or _MANIFEST_DIGEST_PATTERN.fullmatch(sha256) is None:
        raise UpdateError("The update manifest installer SHA-256 is invalid.")
    url = f"{RELEASES_URL}/download/{tag}/{expected_name}"
    validate_asset_url(url, tag=tag, name=expected_name)
    return UpdateAsset(expected_name, url, size, sha256.lower())


def _validate_manifest_url(
    url: str,
    *,
    stage: str,
    manifest_name: str,
) -> str | None:
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
        expected = urlsplit(
            f"https://github.com/loLollipop/FormulaSnip/releases/latest/download/"
            f"{manifest_name}"
        )
        if parsed.hostname != "github.com" or parsed.path != expected.path or parsed.query:
            raise UpdateError("The update manifest latest URL is invalid.")
        return None
    if stage == "tagged":
        if parsed.hostname != "github.com" or parsed.query:
            raise UpdateError("The update manifest did not resolve to a tagged release.")
        match = re.fullmatch(
            r"/loLollipop/FormulaSnip/releases/download/"
            r"(v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))/"
            + re.escape(manifest_name),
            parsed.path,
        )
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


def _read_manifest_response(
    response: Any,
    cancel_event: CancellationSignal | None = None,
    *,
    max_bytes: int = MAX_MANIFEST_BYTES,
) -> object:
    _raise_if_cancelled(cancel_event)
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError) as exc:
            raise UpdateError("The update manifest has an invalid Content-Length.") from exc
        if declared_size < 0 or declared_size > max_bytes:
            raise UpdateError("The update manifest is too large.")

    content = bytearray()
    for chunk in response.iter_content(chunk_size=16 * 1024):
        _raise_if_cancelled(cancel_event)
        if not chunk:
            continue
        if len(content) + len(chunk) > max_bytes:
            raise UpdateError("The update manifest is too large.")
        content.extend(chunk)
    _raise_if_cancelled(cancel_event)
    # requests yields decompressed bytes, while Content-Length describes the
    # encoded representation. Both sizes are capped, but only compare identity.
    encoding = str(response.headers.get("Content-Encoding", "identity")).strip().lower()
    if (
        content_length is not None
        and encoding in {"", "identity"}
        and len(content) != declared_size
    ):
        raise UpdateError("The update response length does not match Content-Length.")
    try:
        return json.loads(bytes(content))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The update manifest is not valid JSON.") from exc


def parse_manifest(
    payload: object,
    *,
    resolved_tag: str,
    current_version: str = __version__,
    installed_model_identity: str | None = None,
) -> ReleaseInfo | None:
    if not isinstance(payload, Mapping):
        raise UpdateError("The update manifest has an invalid schema.")
    schema_version = payload.get("schema_version")
    schema_keys = {
        1: {"schema_version", "version", "tag", "notes", "asset"},
        2: {
            "schema_version",
            "version",
            "tag",
            "notes",
            "asset",
            "update_asset",
            "model_bundle_sha256",
        },
    }
    if type(schema_version) is not int or schema_version not in schema_keys:
        raise UpdateError("The update manifest schema version is unsupported.")
    if set(payload) != schema_keys[schema_version]:
        raise UpdateError("The update manifest has an invalid schema.")

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

    full_asset = _parse_manifest_asset(
        payload.get("asset"), version=version, tag=tag, lightweight=False
    )
    selected_asset = full_asset
    fallback_asset: UpdateAsset | None = None
    if schema_version == 2:
        model_identity = payload.get("model_bundle_sha256")
        if (
            not isinstance(model_identity, str)
            or _MANIFEST_DIGEST_PATTERN.fullmatch(model_identity) is None
        ):
            raise UpdateError("The update manifest model bundle identity is invalid.")
        update_asset = _parse_manifest_asset(
            payload.get("update_asset"), version=version, tag=tag, lightweight=True
        )
        current_identity = (
            installed_model_identity
            if installed_model_identity is not None
            else installed_model_bundle_identity()
        )
        if (
            current_identity is not None
            and current_identity.casefold() == model_identity.casefold()
        ):
            selected_asset = update_asset
            fallback_asset = full_asset
    if version_tuple <= parse_version(current_version):
        return None

    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=notes[:MAX_RELEASE_NOTES_LENGTH],
        asset=selected_asset,
        fallback_asset=fallback_asset,
    )


def _fetch_release_manifest(
    current_version: str,
    *,
    client: HttpClient,
    cancel_event: CancellationSignal | None = None,
    manifest_url: str = LATEST_RELEASE_MANIFEST,
    schema_version: int = 2,
) -> ReleaseInfo | None:
    manifest_name = _MANIFEST_NAMES.get(schema_version)
    if manifest_name is None or manifest_url != (
        "https://github.com/loLollipop/FormulaSnip/releases/latest/download/"
        + manifest_name
    ):
        raise UpdateError("The update manifest source is invalid.")
    current_url = manifest_url
    resolved_tag: str | None = None
    stages = ("latest", "tagged", "asset")
    for redirect_count in range(MAX_MANIFEST_REDIRECTS + 1):
        _raise_if_cancelled(cancel_event)
        response: Any = None
        try:
            stage = stages[redirect_count]
            _validate_manifest_url(
                current_url, stage=stage, manifest_name=manifest_name
            )
            response = client.get(
                current_url,
                headers={"Accept": "application/json", "User-Agent": "FormulaSnip-Updater"},
                timeout=REQUEST_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
            _raise_if_cancelled(cancel_event)
            response_url = str(getattr(response, "url", current_url) or current_url)
            response_tag = _validate_manifest_url(
                response_url, stage=stage, manifest_name=manifest_name
            )
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
                next_tag = _validate_manifest_url(
                    next_url,
                    stage=stages[redirect_count + 1],
                    manifest_name=manifest_name,
                )
                if next_tag is not None:
                    resolved_tag = next_tag
                response.close()
                current_url = next_url
                continue
            response.raise_for_status()
            _raise_if_cancelled(cancel_event)
            if stage != "asset" or resolved_tag is None:
                raise UpdateError("The update manifest did not follow the expected redirects.")
            payload = _read_manifest_response(response, cancel_event)
            if not isinstance(payload, Mapping) or payload.get("schema_version") != schema_version:
                raise UpdateError("The update manifest schema does not match its filename.")
            _raise_if_cancelled(cancel_event)
            return parse_manifest(
                payload,
                resolved_tag=resolved_tag,
                current_version=current_version,
            )
        except requests.RequestException as exc:
            _raise_if_cancelled(cancel_event)
            raise UpdateError("Unable to download the update manifest.") from exc
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
    raise UpdateError("The update manifest used too many redirects.")


def _fetch_release_api(
    current_version: str,
    *,
    client: HttpClient,
    cancel_event: CancellationSignal | None = None,
) -> ReleaseInfo | None:
    response: Any = None
    try:
        _raise_if_cancelled(cancel_event)
        response = client.get(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "FormulaSnip-Updater"},
            timeout=REQUEST_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        _raise_if_cancelled(cancel_event)
        status_code = int(getattr(response, "status_code", 0))
        if 300 <= status_code < 400:
            raise UpdateError("GitHub returned an unexpected redirect for the release API.")
        response.raise_for_status()
        _raise_if_cancelled(cancel_event)
        payload = _read_manifest_response(
            response, cancel_event, max_bytes=MAX_RELEASE_API_BYTES
        )
        _raise_if_cancelled(cancel_event)
    except (requests.RequestException, ValueError) as exc:
        _raise_if_cancelled(cancel_event)
        raise UpdateError("Unable to check the GitHub release API.") from exc
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
    return parse_release(payload, current_version)


def fetch_latest_release(
    current_version: str = __version__,
    *,
    client: HttpClient = requests,
    cancel_event: CancellationSignal | None = None,
) -> ReleaseInfo | None:
    """Bound the entire check, including DNS and slow response bodies.

    DNS itself cannot be interrupted by requests. Slots remain occupied until
    the real transport finishes, preventing repeated timeouts spawning leaks.
    """
    _raise_if_cancelled(cancel_event)
    if not _CHECK_TRANSPORT_SLOTS.acquire(blocking=False):
        raise UpdateError("更新连接仍在结束，请稍后重试。")
    cancellation = UpdateCancellation()
    finished = Event()
    state: dict[str, Any] = {}

    def transfer() -> None:
        try:
            state["release"] = _fetch_latest_release(
                current_version, client=client, cancel_event=cancellation
            )
        except Exception as exc:
            state["error"] = exc
        finally:
            _CHECK_TRANSPORT_SLOTS.release()
            finished.set()

    worker = Thread(target=transfer, name="FormulaSnip update check", daemon=True)
    deadline = monotonic() + UPDATE_CHECK_TIMEOUT_SECONDS
    try:
        worker.start()
    except Exception:
        _CHECK_TRANSPORT_SLOTS.release()
        raise
    try:
        while not finished.is_set():
            _raise_if_cancelled(cancel_event)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise UpdateError("检查更新超时，请稍后重试。")
            finished.wait(min(0.02, remaining))
        _raise_if_cancelled(cancel_event)
        if monotonic() > deadline:
            raise UpdateError("检查更新超时，请稍后重试。")
    except UpdateError:
        cancellation.cancel()
        worker.join(timeout=0.15)
        raise
    if "error" in state:
        raise state["error"]
    return state["release"]


def _fetch_latest_release(
    current_version: str,
    *,
    client: HttpClient,
    cancel_event: CancellationSignal,
) -> ReleaseInfo | None:
    _raise_if_cancelled(cancel_event)
    with _request_client(client, cancel_event) as request_client:
        for manifest_url, schema_version in (
            (LATEST_RELEASE_MANIFEST, 2),
            (LEGACY_RELEASE_MANIFEST, 1),
        ):
            try:
                return _fetch_release_manifest(
                    current_version,
                    client=request_client,
                    cancel_event=cancel_event,
                    manifest_url=manifest_url,
                    schema_version=schema_version,
                )
            except UpdateCancelled:
                raise
            except UpdateError:
                _raise_if_cancelled(cancel_event)
        try:
            return _fetch_release_api(
                current_version,
                client=request_client,
                cancel_event=cancel_event,
            )
        except UpdateCancelled:
            raise
        except UpdateError as api_error:
            _raise_if_cancelled(cancel_event)
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


def _sha256_file(
    path: Path,
    cancel_event: CancellationSignal | None = None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            _raise_if_cancelled(cancel_event)
            digest.update(chunk)
    _raise_if_cancelled(cancel_event)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class _InstallerVerification:
    asset_sha256: str
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int


_VERIFIED_INSTALLERS: dict[Path, _InstallerVerification] = {}
_VERIFIED_INSTALLER_HANDLES: dict[Path, int] = {}
_VERIFIED_INSTALLERS_LOCK = Lock()


def _installer_cache_key(path: Path) -> Path:
    return path.absolute()


def _installer_verification(
    stat: os.stat_result,
    asset: UpdateAsset,
) -> _InstallerVerification:
    return _InstallerVerification(
        asset_sha256=asset.sha256,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        ctime_ns=stat.st_ctime_ns,
        device=stat.st_dev,
        inode=stat.st_ino,
    )


def _open_installer_read_lock(path: Path) -> int | None:
    """Deny writes/deletes until CreateProcess has opened the verified file."""

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(
        str(path),
        0x80000000,  # GENERIC_READ
        0x00000001,  # FILE_SHARE_READ: deny write and delete sharing
        None,
        3,  # OPEN_EXISTING
        0x00000080,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if not handle or int(handle) == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, "Unable to lock the cached installer for verification")
    return int(handle)


def _close_installer_read_lock(handle: int | None) -> None:
    if handle is None or sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(wintypes.HANDLE(handle))


def _forget_verified_installer(path: Path) -> None:
    handle: int | None
    with _VERIFIED_INSTALLERS_LOCK:
        key = _installer_cache_key(path)
        _VERIFIED_INSTALLERS.pop(key, None)
        handle = _VERIFIED_INSTALLER_HANDLES.pop(key, None)
    _close_installer_read_lock(handle)


def release_verified_installer(path: Path) -> None:
    """Release any retained verification and deny-write lock for ``path``.

    The operation is safe to repeat, including for paths that were never
    retained or whose lock has already been consumed by installer launch.
    """

    _forget_verified_installer(Path(path))


def _has_current_installer_verification(path: Path, asset: UpdateAsset) -> bool:
    if path.name != asset.name:
        _forget_verified_installer(path)
        return False
    try:
        path.resolve(strict=True)
        stat = path.stat()
    except OSError:
        _forget_verified_installer(path)
        return False
    if stat.st_size != asset.size:
        _forget_verified_installer(path)
        return False
    current = _installer_verification(stat, asset)
    with _VERIFIED_INSTALLERS_LOCK:
        key = _installer_cache_key(path)
        remembered = _VERIFIED_INSTALLERS.get(key)
        handle_present = (
            sys.platform != "win32"
            or key in _VERIFIED_INSTALLER_HANDLES
        )
        if remembered != current or not handle_present:
            _VERIFIED_INSTALLERS.pop(key, None)
            stale_handle = _VERIFIED_INSTALLER_HANDLES.pop(key, None)
            _close_installer_read_lock(stale_handle)
            return False
    return True


def verify_installer(
    path: Path,
    asset: UpdateAsset,
    *,
    cancel_event: CancellationSignal | None = None,
    retain_lock: bool = False,
) -> None:
    _raise_if_cancelled(cancel_event)
    _forget_verified_installer(path)
    if path.name != asset.name:
        raise UpdateError("The cached installer path is invalid.")
    read_lock: int | None = None
    try:
        try:
            read_lock = _open_installer_read_lock(path)
            resolved = path.resolve(strict=True)
            before = path.stat()
        except OSError as exc:
            raise UpdateError("The cached installer cannot be inspected.") from exc
        if not path.is_file():
            raise UpdateError("The cached installer path is invalid.")
        if before.st_size != asset.size:
            raise UpdateError(
                "The installer size does not match the GitHub release metadata."
            )
        try:
            digest = _sha256_file(path, cancel_event)
            after_resolved = path.resolve(strict=True)
            after = path.stat()
        except UpdateCancelled:
            _forget_verified_installer(path)
            raise
        except OSError as exc:
            _forget_verified_installer(path)
            raise UpdateError("The cached installer changed during verification.") from exc
        verification = _installer_verification(before, asset)
        if after_resolved != resolved or _installer_verification(after, asset) != verification:
            _forget_verified_installer(path)
            raise UpdateError("The cached installer changed during verification.")
        if digest != asset.sha256:
            raise UpdateError("The installer SHA-256 digest does not match GitHub metadata.")
        if retain_lock:
            with _VERIFIED_INSTALLERS_LOCK:
                key = _installer_cache_key(path)
                _VERIFIED_INSTALLERS[key] = verification
                if read_lock is not None:
                    _VERIFIED_INSTALLER_HANDLES[key] = read_lock
            read_lock = None
    finally:
        # The handle becomes cache-owned only after a complete successful
        # verification. Every cancellation and unexpected failure must release
        # a still-local deny-write handle.
        _close_installer_read_lock(read_lock)


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
    # Download workers perform the final full SHA-256 pass after publishing the
    # file. On the GUI thread, only accept that result while stable filesystem
    # identity and timestamps still match; otherwise fall back to a full check.
    if not _has_current_installer_verification(path, asset):
        verify_installer(path, asset, retain_lock=True)
    try:
        result = start_detached(str(path), list(INSTALLER_ARGUMENTS))
    finally:
        # CreateProcess/startDetached has opened the executable before it
        # returns; only then release the deny-write/delete handle.
        _forget_verified_installer(path)
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


def _open_trusted_download(
    asset: UpdateAsset,
    *,
    tag: str,
    client: HttpClient,
    cancel_event: CancellationSignal | None = None,
) -> Any:
    current_url = asset.url
    for redirect_count in range(MAX_DOWNLOAD_REDIRECTS + 1):
        _raise_if_cancelled(cancel_event)
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
            _raise_if_cancelled(cancel_event)
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
            _raise_if_cancelled(cancel_event)
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
    cancel_event: CancellationSignal | None = None,
) -> Path:
    _raise_if_cancelled(cancel_event)
    with _request_client(client, cancel_event) as request_client:
        return _download_installer(
            asset,
            cache_directory,
            client=request_client,
            progress=progress,
            cancel_event=cancel_event,
        )


def _download_installer(
    asset: UpdateAsset,
    cache_directory: Path,
    *,
    client: HttpClient,
    progress: Callable[[int, int], None] | None,
    cancel_event: CancellationSignal | None,
) -> Path:
    tag = _asset_tag(asset)
    validate_asset_url(asset.url, tag=tag, name=asset.name)
    _raise_if_cancelled(cancel_event)
    cache_directory.mkdir(parents=True, exist_ok=True)
    destination = cache_directory / asset.name
    partial = cache_directory / (
        f".{asset.name}.{os.getpid()}.{uuid4().hex}.part"
    )
    if destination.is_file():
        try:
            verify_installer(
                destination,
                asset,
                cancel_event=cancel_event,
                retain_lock=True,
            )
            _raise_if_cancelled(cancel_event)
            if progress is not None:
                progress(asset.size, asset.size)
            _prune_retired_installers(cache_directory, asset.name)
            return destination
        except UpdateCancelled:
            # Verification may have completed and transferred its Windows
            # deny-write handle to the cache just before cancellation won the
            # race. The cancelled caller will never launch this installer, so
            # release that ownership while keeping the valid file for retry.
            _forget_verified_installer(destination)
            raise
        except UpdateError:
            _forget_verified_installer(destination)
            destination.unlink(missing_ok=True)
    response: Any = None
    downloaded = 0
    digest = hashlib.sha256()
    try:
        response = _open_trusted_download(
            asset,
            tag=tag,
            client=client,
            cancel_event=cancel_event,
        )
        _raise_if_cancelled(cancel_event)
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
                _raise_if_cancelled(cancel_event)
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > asset.size:
                    raise UpdateError("The installer is larger than its GitHub metadata.")
                digest.update(chunk)
                handle.write(chunk)
                _raise_if_cancelled(cancel_event)
                if progress is not None:
                    progress(downloaded, asset.size)
        _raise_if_cancelled(cancel_event)
        if downloaded != asset.size:
            raise UpdateError("The installer download is incomplete.")
        _raise_if_cancelled(cancel_event)
        if digest.hexdigest() != asset.sha256:
            raise UpdateError("The installer SHA-256 digest does not match GitHub metadata.")
        _raise_if_cancelled(cancel_event)
        os.replace(partial, destination)
        _forget_verified_installer(destination)
        verify_installer(
            destination,
            asset,
            cancel_event=cancel_event,
            retain_lock=True,
        )
        _prune_retired_installers(cache_directory, asset.name)
        return destination
    except requests.RequestException as exc:
        _raise_if_cancelled(cancel_event)
        raise UpdateError("Unable to download the installer.") from exc
    except OSError as exc:
        _raise_if_cancelled(cancel_event)
        raise UpdateError("Unable to save the installer in the user cache.") from exc
    finally:
        partial.unlink(missing_ok=True)
        if response is not None and callable(getattr(response, "close", None)):
            response.close()


def _prune_retired_installers(cache_directory: Path, current_name: str) -> None:
    """Best-effort cleanup of older FormulaSnip installers in the update cache."""

    current_match = _INSTALLER_PATTERN.fullmatch(current_name)
    if current_match is None:
        return
    current_version = parse_version(current_match.group(1))
    try:
        entries = tuple(cache_directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name == current_name or not entry.is_file():
            continue
        candidate_match = _INSTALLER_PATTERN.fullmatch(entry.name)
        if candidate_match is None:
            continue
        if parse_version(candidate_match.group(1)) >= current_version:
            continue
        try:
            _forget_verified_installer(entry)
            entry.unlink()
        except OSError:
            continue
