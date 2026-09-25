from __future__ import annotations

import hashlib
import json
import socket
import sys
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any

import pytest
import requests
from PySide6.QtCore import Qt

from formulasnip import update as update_module
from formulasnip.update import (
    INSTALLER_ARGUMENTS,
    LATEST_RELEASE_API,
    LATEST_RELEASE_MANIFEST,
    LEGACY_RELEASE_MANIFEST,
    MAX_MANIFEST_BYTES,
    REQUEST_TIMEOUT,
    ReleaseInfo,
    UpdateAsset,
    UpdateCancellation,
    UpdateCancelled,
    UpdateError,
    _fetch_release_manifest,
    download_installer,
    fetch_latest_release,
    installed_model_bundle_identity,
    is_installed_build,
    is_newer_version,
    launch_verified_installer,
    parse_manifest,
    parse_release,
    parse_version,
    release_verified_installer,
    should_check_for_updates,
    validate_asset_url,
    verify_installer,
)

MANIFEST_NAME = "FormulaSnip-update-v2.json"
LEGACY_MANIFEST_NAME = "FormulaSnip-update.json"


def _payload(
    *,
    tag: str = "v0.3.0",
    digest: str = "sha256:" + "a" * 64,
    size: int = 123,
    draft: bool = False,
    prerelease: bool = False,
) -> dict[str, Any]:
    version = tag.removeprefix("v")
    name = f"FormulaSnip-v{version}-windows-x64-setup.exe"
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "body": "changes",
        "assets": [
            {
                "name": name,
                "browser_download_url": (
                    f"https://github.com/loLollipop/FormulaSnip/releases/download/{tag}/{name}"
                ),
                "size": size,
                "digest": digest,
            }
        ],
    }


def _manifest(
    *,
    version: str = "0.3.0",
    tag: str | None = None,
    name: str | None = None,
    size: int = 123,
    sha256: str = "a" * 64,
    notes: str = "changes",
) -> dict[str, Any]:
    resolved_tag = tag if tag is not None else f"v{version}"
    return {
        "schema_version": 1,
        "version": version,
        "tag": resolved_tag,
        "notes": notes,
        "asset": {
            "name": name or f"FormulaSnip-v{version}-windows-x64-setup.exe",
            "size": size,
            "sha256": sha256,
        },
    }


def _manifest_v2(*, model_identity: str = "b" * 64) -> dict[str, Any]:
    payload = _manifest()
    payload["schema_version"] = 2
    payload["model_bundle_sha256"] = model_identity
    payload["update_asset"] = {
        "name": "FormulaSnip-v0.3.0-windows-x64-update.exe",
        "size": 45,
        "sha256": "c" * 64,
    }
    return payload


def _manifest_responses(
    payload: object | None = None,
    *,
    tag: str = "v0.3.0",
) -> list[_Response]:
    tagged_url = (
        f"https://github.com/loLollipop/FormulaSnip/releases/download/{tag}/{MANIFEST_NAME}"
    )
    asset_url = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1371591206/manifest-asset?signed=1"
    )
    body = json.dumps(_manifest_v2() if payload is None else payload).encode()
    return [
        _Response(url=LATEST_RELEASE_MANIFEST, status_code=302, location=tagged_url),
        _Response(url=tagged_url, status_code=302, location=asset_url),
        _Response(
            content=body,
            url=asset_url,
            content_length=len(body),
        ),
    ]


def _legacy_manifest_responses(payload: object | None = None) -> list[_Response]:
    tagged_url = (
        "https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        + LEGACY_MANIFEST_NAME
    )
    asset_url = (
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1371591206/legacy-manifest?signed=1"
    )
    body = json.dumps(_manifest() if payload is None else payload).encode()
    return [
        _Response(url=LEGACY_RELEASE_MANIFEST, status_code=302, location=tagged_url),
        _Response(url=tagged_url, status_code=302, location=asset_url),
        _Response(content=body, url=asset_url, content_length=len(body)),
    ]


def test_version_comparison_and_release_policy() -> None:
    assert parse_version("v2.10.3", tag=True) == (2, 10, 3)
    assert is_newer_version("0.2.1", "0.2.0")
    assert not is_newer_version("0.2.0", "0.2.0")
    for invalid in ("0.3.0", "v0.3", "v0.3.0-beta", "v01.3.0"):
        with pytest.raises(UpdateError):
            parse_version(invalid, tag=True)
    with pytest.raises(UpdateError):
        parse_version("v" + "9" * 5_000 + ".0.0", tag=True)

    assert parse_release(_payload(draft=True), "0.2.0") is None
    assert parse_release(_payload(prerelease=True), "0.2.0") is None
    assert parse_release(_payload(tag="v0.2.0"), "0.2.0") is None


def test_update_session_is_anonymous_without_disabling_environment(
    monkeypatch: Any,
) -> None:
    netrc_lookups: list[str] = []
    monkeypatch.setattr(
        requests.sessions,
        "get_netrc_auth",
        lambda url: netrc_lookups.append(url) or ("netrc-user", "netrc-password"),
    )

    with update_module._request_client(requests, None) as session:
        assert session.trust_env is True
        prepared = session.prepare_request(
            requests.Request("GET", "https://api.github.com/repos/example/releases")
        )

    assert "Authorization" not in prepared.headers
    assert netrc_lookups == []


def test_injected_update_session_is_wrapped_with_anonymous_auth(
    monkeypatch: Any,
) -> None:
    netrc_lookups: list[str] = []
    monkeypatch.setattr(
        requests.sessions,
        "get_netrc_auth",
        lambda url: netrc_lookups.append(url) or ("netrc-user", "netrc-password"),
    )
    class CapturingSession(requests.Session):
        def __init__(self) -> None:
            super().__init__()
            self.prepared: requests.PreparedRequest | None = None

        def get(self, url: str, **kwargs: Any) -> object:
            self.prepared = self.prepare_request(
                requests.Request(
                    "GET",
                    url,
                    headers=kwargs.get("headers"),
                    auth=kwargs.get("auth"),
                )
            )
            return object()

    session = CapturingSession()
    with update_module._request_client(session, None) as client:
        client.get("https://api.github.com/repos/example/releases")

    assert session.prepared is not None
    assert "Authorization" not in session.prepared.headers
    assert netrc_lookups == []


def test_release_json_requires_one_exact_safe_asset_and_digest() -> None:
    release = parse_release(_payload(), "0.2.0")
    assert isinstance(release, ReleaseInfo)
    assert release.version == "0.3.0"
    assert release.asset.name == "FormulaSnip-v0.3.0-windows-x64-setup.exe"

    missing = _payload()
    missing["assets"] = []
    with pytest.raises(UpdateError, match="exactly one"):
        parse_release(missing, "0.2.0")

    duplicate = _payload()
    duplicate["assets"].append(dict(duplicate["assets"][0]))
    with pytest.raises(UpdateError, match="exactly one"):
        parse_release(duplicate, "0.2.0")

    for digest in ("", "a" * 64, "sha256:xyz", None):
        with pytest.raises(UpdateError, match="SHA-256"):
            parse_release(_payload(digest=digest), "0.2.0")  # type: ignore[arg-type]
    with pytest.raises(UpdateError, match="size"):
        parse_release(_payload(size=0), "0.2.0")


def test_asset_url_restrictions() -> None:
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    validate_asset_url(
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        tag="v0.3.0",
        name=name,
    )
    for url in (
        f"http://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        f"https://evil.example/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        f"https://github.com/other/FormulaSnip/releases/download/v0.3.0/{name}",
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}?x=1",
    ):
        with pytest.raises(UpdateError):
            validate_asset_url(url, tag="v0.3.0", name=name)

    validate_asset_url(
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/1371591206/26d55823-a599-4d0a-943c-5e244e54d9c1"
        "?signed=1",
        tag="v0.3.0",
        name=name,
        allow_redirect=True,
    )


class _Response:
    def __init__(
        self,
        *,
        payload: object | None = None,
        content: bytes = b"",
        url: str = "",
        content_length: int | None = None,
        status_code: int = 200,
        location: str | None = None,
        raise_error: requests.RequestException | None = None,
    ) -> None:
        self._payload = payload
        self._content = json.dumps(payload).encode() if payload is not None else content
        self.url = url
        self.status_code = status_code
        self.raise_error = raise_error
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        if location is not None:
            self.headers["Location"] = location
        self.closed = False

    def raise_for_status(self) -> None:
        if self.raise_error is not None:
            raise self.raise_error
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [
            self._content[index : index + chunk_size]
            for index in range(0, len(self._content), chunk_size)
        ]

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, response: _Response | list[_Response]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        if len(self.calls) > len(self.responses):
            raise AssertionError(f"Unexpected request: {url}")
        return self.responses[len(self.calls) - 1]


def test_manifest_schema_constructs_trusted_download_url() -> None:
    release = parse_manifest(
        _manifest(sha256="A" * 64),
        resolved_tag="v0.3.0",
        current_version="0.2.0",
    )
    assert isinstance(release, ReleaseInfo)
    assert release.version == "0.3.0"
    assert release.asset.url == (
        "https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    )
    assert release.asset.sha256 == "a" * 64


@pytest.mark.parametrize("declared", [None, "1", "invalid", "9999999", "-1"])
def test_api_fallback_rejects_oversized_or_invalid_lengths(declared: str | None) -> None:
    response = _Response(content=b"x" * (update_module.MAX_RELEASE_API_BYTES + 1))
    if declared is not None:
        response.headers["Content-Length"] = declared
    with pytest.raises(UpdateError):
        update_module._fetch_release_api("0.2.0", client=_Client(response))
    assert response.closed


def test_api_fallback_reads_bounded_json_without_response_json(monkeypatch: Any) -> None:
    response = _Response(payload=_payload())
    monkeypatch.setattr(response, "json", lambda: pytest.fail("unbounded json"))
    release = update_module._fetch_release_api("0.2.0", client=_Client(response))
    assert release is not None and release.version == "0.3.0"
    assert response.closed


def test_api_compressed_content_length_uses_decompressed_size_limit() -> None:
    response = _Response(payload=_payload(), content_length=20)
    response.headers["Content-Encoding"] = "gzip"
    release = update_module._fetch_release_api("0.2.0", client=_Client(response))
    assert release is not None and response.closed


def test_update_total_deadline_bounds_slow_drip_and_closes_response(monkeypatch: Any) -> None:
    import time

    class SlowResponse(_Response):
        def iter_content(self, chunk_size: int):
            while True:
                time.sleep(0.01)
                yield b" "

    response = SlowResponse()
    monkeypatch.setattr(update_module, "UPDATE_CHECK_TIMEOUT_SECONDS", 0.06)
    client = _Client([_Response(status_code=503), _Response(status_code=503), response])
    start = monotonic()
    with pytest.raises(UpdateError, match="超时"):
        fetch_latest_release("0.2.0", client=client)
    assert monotonic() - start < 0.5
    assert response.closed


def test_manifest_selects_lightweight_update_only_for_matching_model() -> None:
    matching = parse_manifest(
        _manifest_v2(),
        resolved_tag="v0.3.0",
        current_version="0.2.0",
        installed_model_identity="b" * 64,
    )
    mismatching = parse_manifest(
        _manifest_v2(),
        resolved_tag="v0.3.0",
        current_version="0.2.0",
        installed_model_identity="d" * 64,
    )

    assert matching is not None and matching.is_lightweight_update
    assert matching.asset.name.endswith("-windows-x64-update.exe")
    assert matching.fallback_asset is not None
    assert matching.fallback_asset.name.endswith("-windows-x64-setup.exe")
    assert mismatching is not None and not mismatching.is_lightweight_update
    assert mismatching.asset.name.endswith("-windows-x64-setup.exe")
    assert mismatching.fallback_asset is None


def test_manifest_rejects_noncanonical_lightweight_update_asset() -> None:
    payload = _manifest_v2()
    payload["update_asset"]["name"] = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    with pytest.raises(UpdateError, match="filename"):
        parse_manifest(
            payload,
            resolved_tag="v0.3.0",
            current_version="0.2.0",
            installed_model_identity="b" * 64,
        )


def test_same_size_corrupt_installed_model_forces_full_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_root = tmp_path / "frozen"
    model_root = frozen_root / "MathCraft" / "models"
    model_path = model_root / "mathcraft-formula-rec" / "model.onnx"
    model_path.parent.mkdir(parents=True)
    expected = b"expected-model"
    model_path.write_bytes(b"corrupt-model!")
    assert len(model_path.read_bytes()) == len(expected)
    lock_path = frozen_root / "MODEL_ASSETS.json"
    lock_path.write_text(
        json.dumps(
            {
                "model_id": "mathcraft-formula-rec",
                "files": [
                    {
                        "path": "model.onnx",
                        "size": len(expected),
                        "sha256": hashlib.sha256(expected).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_module.sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert installed_model_bundle_identity() is None
    release = parse_manifest(
        _manifest_v2(model_identity=hashlib.sha256(lock_path.read_bytes()).hexdigest()),
        resolved_tag="v0.3.0",
        current_version="0.2.0",
    )

    assert release is not None
    assert not release.is_lightweight_update
    assert release.fallback_asset is None


def test_static_manifest_success_does_not_call_release_api() -> None:
    client = _Client(_manifest_responses())
    release = fetch_latest_release("0.2.0", client=client)
    assert release is not None
    assert len(client.calls) == 3
    assert all(url != LATEST_RELEASE_API for url, _ in client.calls)


def test_v2_static_failure_falls_back_to_legacy_v1_manifest() -> None:
    v2_failure = _Response(url=LATEST_RELEASE_MANIFEST, status_code=404)
    legacy_responses = _legacy_manifest_responses()
    client = _Client([v2_failure, *legacy_responses])

    release = fetch_latest_release("0.2.0", client=client)

    assert release is not None
    assert not release.is_lightweight_update
    assert release.fallback_asset is None
    assert [url for url, _ in client.calls] == [
        LATEST_RELEASE_MANIFEST,
        *[response.url for response in legacy_responses],
    ]
    assert all(url != LATEST_RELEASE_API for url, _ in client.calls)


def test_manifest_follows_complete_redirect_chain_with_safety_options() -> None:
    responses = _manifest_responses()
    client = _Client(responses)

    release = _fetch_release_manifest("0.2.0", client=client)

    assert release is not None
    assert [call[0] for call in client.calls] == [response.url for response in responses]
    assert all(call[1]["timeout"] == REQUEST_TIMEOUT for call in client.calls)
    assert all(call[1]["stream"] is True for call in client.calls)
    assert all(call[1]["allow_redirects"] is False for call in client.calls)
    assert all(response.closed for response in responses)


def test_manifest_rejects_tag_mismatch() -> None:
    with pytest.raises(UpdateError, match="does not match"):
        parse_manifest(
            _manifest(tag="v0.3.1"),
            resolved_tag="v0.3.0",
            current_version="0.2.0",
        )


@pytest.mark.parametrize(
    "location",
    [
        "https://[bad",
        "http://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        + MANIFEST_NAME,
        "https://user:pass@github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        + MANIFEST_NAME,
        "https://github.com:444/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        + MANIFEST_NAME,
        "https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        + MANIFEST_NAME
        + "?unexpected=1",
        "https://evil.example/releases/download/v0.3.0/" + MANIFEST_NAME,
    ],
)
def test_manifest_rejects_malicious_first_redirect(location: str) -> None:
    response = _Response(
        url=LATEST_RELEASE_MANIFEST,
        status_code=302,
        location=location,
    )
    with pytest.raises(UpdateError):
        _fetch_release_manifest("0.2.0", client=_Client(response))
    assert response.closed


@pytest.mark.parametrize("failure", ["oversized", "non-json", "not-found"])
def test_manifest_rejects_invalid_responses(failure: str) -> None:
    responses = _manifest_responses()
    if failure == "oversized":
        responses[-1] = _Response(
            content=b"{}",
            url=responses[-1].url,
            content_length=MAX_MANIFEST_BYTES + 1,
        )
    elif failure == "non-json":
        responses[-1] = _Response(content=b"not-json", url=responses[-1].url)
    else:
        responses[-1] = _Response(url=responses[-1].url, status_code=404)

    with pytest.raises(UpdateError):
        _fetch_release_manifest("0.2.0", client=_Client(responses))
    assert all(response.closed for response in responses)


def test_static_failure_falls_back_to_release_api() -> None:
    static_failure = _Response(url=LATEST_RELEASE_MANIFEST, status_code=404)
    legacy_failure = _Response(url=LEGACY_RELEASE_MANIFEST, status_code=404)
    api_response = _Response(payload=_payload(), url=LATEST_RELEASE_API)
    client = _Client([static_failure, legacy_failure, api_response])

    release = fetch_latest_release("0.2.0", client=client)

    assert release is not None
    assert release.version == "0.3.0"
    assert [url for url, _ in client.calls] == [
        LATEST_RELEASE_MANIFEST,
        LEGACY_RELEASE_MANIFEST,
        LATEST_RELEASE_API,
    ]
    assert static_failure.closed
    assert legacy_failure.closed
    assert api_response.closed


def test_both_update_channels_fail_with_friendly_error() -> None:
    static_failure = _Response(url=LATEST_RELEASE_MANIFEST, status_code=404)
    legacy_failure = _Response(url=LEGACY_RELEASE_MANIFEST, status_code=404)
    api_failure = _Response(url=LATEST_RELEASE_API, status_code=403)
    client = _Client([static_failure, legacy_failure, api_failure])

    with pytest.raises(UpdateError, match="无法检查更新"):
        fetch_latest_release("0.2.0", client=client)

    assert len(client.calls) == 3
    assert static_failure.closed
    assert legacy_failure.closed
    assert api_failure.closed


def test_download_streams_verifies_and_atomically_renames(tmp_path: Path) -> None:
    content = b"trusted installer"
    sha256 = hashlib.sha256(content).hexdigest()
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, len(content), sha256)
    class ChunkedResponse(_Response):
        def iter_content(self, chunk_size: int) -> list[bytes]:
            del chunk_size
            return [content[:7], content[7:]]

    response = ChunkedResponse(
        content=content,
        url=(
            "https://release-assets.githubusercontent.com/"
            "github-production-release-asset/1/test-asset"
        ),
    )
    redirect = _Response(
        url=url,
        status_code=302,
        location=response.url,
    )
    client = _Client([redirect, response])
    progress: list[tuple[int, int]] = []

    path = download_installer(
        asset,
        tmp_path,
        client=client,
        progress=lambda received, total: progress.append((received, total)),
    )

    assert path.read_bytes() == content
    assert progress == [(7, len(content)), (len(content), len(content))]
    assert not list(tmp_path.glob("*.part"))
    assert len(client.calls) == 2
    assert all(call[1]["stream"] is True for call in client.calls)
    assert all(call[1]["allow_redirects"] is False for call in client.calls)
    assert client.calls[0][1]["timeout"] == REQUEST_TIMEOUT


def test_download_network_failure_keeps_a_retryable_user_message(
    tmp_path: Path,
) -> None:
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, 5, "0" * 64)
    response = _Response(
        url=url,
        raise_error=requests.ConnectionError("offline"),
    )

    with pytest.raises(UpdateError, match="检查网络后重试"):
        download_installer(asset, tmp_path, client=_Client(response))

    assert response.closed
    assert not list(tmp_path.glob("*.part"))


def test_download_rejects_untrusted_redirect_before_following_it(tmp_path: Path) -> None:
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, 5, "0" * 64)
    redirect = _Response(
        url=url,
        status_code=302,
        location="https://evil.example/setup.exe",
    )
    client = _Client(redirect)

    with pytest.raises(UpdateError, match="allowed GitHub"):
        download_installer(asset, tmp_path, client=client)

    assert len(client.calls) == 1
    assert redirect.closed


@pytest.mark.parametrize("reported_size", [1, 99])
def test_download_rejects_size_mismatch_and_cleans_partial(
    tmp_path: Path, reported_size: int
) -> None:
    content = b"abc"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, reported_size, hashlib.sha256(content).hexdigest())
    response = _Response(content=content, url=url, content_length=len(content))
    with pytest.raises(UpdateError):
        download_installer(asset, tmp_path, client=_Client(response))
    assert not list(tmp_path.glob("*.part"))


def test_cancelled_download_cleans_partial_and_stops_progress(tmp_path: Path) -> None:
    content = b"abcdef"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, len(content), hashlib.sha256(content).hexdigest())
    cancellation = UpdateCancellation()

    class CancellingResponse(_Response):
        def iter_content(self, chunk_size: int) -> Any:
            del chunk_size
            yield content[:3]
            cancellation.cancel()
            yield content[3:]

    progress: list[tuple[int, int]] = []
    response = CancellingResponse(content=content, url=url, content_length=len(content))

    with pytest.raises(UpdateCancelled):
        download_installer(
            asset,
            tmp_path,
            client=_Client(response),
            progress=lambda received, total: progress.append((received, total)),
            cancel_event=cancellation,
        )

    assert progress == [(3, 6)]
    assert not list(tmp_path.glob("*.part"))
    assert not (tmp_path / name).exists()
    assert response.closed


def test_cancelled_cached_installer_verification_preserves_complete_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import formulasnip.update as update_module

    content = b"complete cached installer"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    destination = tmp_path / name
    destination.write_bytes(content)
    asset = UpdateAsset(
        name,
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )

    def cancel_during_hash(
        _path: Path,
        _cancel_event: object,
    ) -> str:
        raise UpdateCancelled("cancelled during hash")

    monkeypatch.setattr(update_module, "_sha256_file", cancel_during_hash)

    with pytest.raises(UpdateCancelled):
        download_installer(
            asset,
            tmp_path,
            cancel_event=UpdateCancellation(),
        )

    assert destination.read_bytes() == content


def test_cached_installer_reports_verification_without_fake_download_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"complete cached installer"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    destination = tmp_path / name
    destination.write_bytes(content)
    asset = UpdateAsset(
        name,
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    progress: list[tuple[int, int]] = []
    phases: list[str] = []

    def verify_after_progress(*_args: object, **_kwargs: object) -> None:
        assert phases == ["verifying-cache"]
        assert progress == []

    monkeypatch.setattr(update_module, "verify_installer", verify_after_progress)

    assert download_installer(
        asset,
        tmp_path,
        progress=lambda received, total: progress.append((received, total)),
        phase=phases.append,
    ) == destination
    assert phases == ["verifying-cache"]
    assert progress == []


def test_invalid_cached_installer_resets_then_reports_network_bytes(
    tmp_path: Path,
) -> None:
    content = b"trusted replacement"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    destination = tmp_path / name
    destination.write_bytes(b"corrupt cached file")
    asset = UpdateAsset(
        name,
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )

    class ChunkedResponse(_Response):
        def iter_content(self, chunk_size: int) -> list[bytes]:
            del chunk_size
            return [content[:7], content[7:]]

    response = ChunkedResponse(content=content, url=asset.url)
    progress: list[tuple[int, int]] = []
    phases: list[str] = []

    assert download_installer(
        asset,
        tmp_path,
        client=_Client(response),
        progress=lambda received, total: progress.append((received, total)),
        phase=phases.append,
    ) == destination
    assert phases == ["verifying-cache", "downloading", "verifying"]
    assert progress == [
        (0, len(content)),
        (7, len(content)),
        (len(content), len(content)),
    ]
    assert destination.read_bytes() == content


def test_cancelled_after_cached_verification_releases_retained_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import formulasnip.update as update_module

    content = b"complete cached installer"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    destination = tmp_path / name
    destination.write_bytes(content)
    asset = UpdateAsset(
        name,
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    cancellation = UpdateCancellation()
    original_verify = update_module.verify_installer

    def cancel_after_verification(*args: object, **kwargs: object) -> None:
        original_verify(*args, **kwargs)
        cancellation.cancel()

    monkeypatch.setattr(update_module, "verify_installer", cancel_after_verification)

    with pytest.raises(UpdateCancelled):
        download_installer(asset, tmp_path, cancel_event=cancellation)

    key = update_module._installer_cache_key(destination)
    assert destination.read_bytes() == content
    assert key not in update_module._VERIFIED_INSTALLERS
    assert key not in update_module._VERIFIED_INSTALLER_HANDLES


def test_successful_cached_installer_prunes_only_older_formula_installers(
    tmp_path: Path,
) -> None:
    content = b"current cached installer"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    destination = tmp_path / name
    destination.write_bytes(content)
    old_installer = tmp_path / "FormulaSnip-v0.2.6-windows-x64-setup.exe"
    old_installer.write_bytes(b"old")
    newer_installer = tmp_path / "FormulaSnip-v0.4.0-windows-x64-setup.exe"
    newer_installer.write_bytes(b"newer")
    unrelated = tmp_path / "AnotherApp-v1.0.0-windows-x64-setup.exe"
    unrelated.write_bytes(b"keep")
    partial = tmp_path / ".FormulaSnip-v0.2.5-windows-x64-setup.exe.part"
    partial.write_bytes(b"keep partial")
    asset = UpdateAsset(
        name,
        f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )

    assert download_installer(asset, tmp_path) == destination

    assert destination.read_bytes() == content
    assert not old_installer.exists()
    assert newer_installer.read_bytes() == b"newer"
    assert unrelated.read_bytes() == b"keep"
    assert partial.read_bytes() == b"keep partial"


def test_cancelled_update_worker_emits_no_completion_signal(monkeypatch: Any) -> None:
    from formulasnip.ui import update_dialog

    entered = Event()

    def blocking_fetch(
        _version: str, *, cancel_event: UpdateCancellation
    ) -> ReleaseInfo | None:
        entered.set()
        released = Event()
        cancel_event.add_abort_callback(released.set)
        assert released.wait(1.0)
        raise UpdateCancelled("cancelled")

    monkeypatch.setattr(update_dialog, "fetch_latest_release", blocking_fetch)
    worker = update_dialog.UpdateCheckWorker("0.2.0")
    emitted: list[str] = []
    direct = Qt.ConnectionType.DirectConnection
    worker.signals.available.connect(
        lambda _release: emitted.append("available"), type=direct
    )
    worker.signals.no_update.connect(lambda: emitted.append("none"), type=direct)
    worker.signals.failed.connect(
        lambda _message: emitted.append("failed"), type=direct
    )
    thread = Thread(target=worker.run)
    thread.start()
    assert entered.wait(1.0)

    worker.cancel()
    thread.join(1.0)

    assert not thread.is_alive()
    assert emitted == []


def test_update_check_worker_abandons_blocked_dns_after_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from formulasnip.ui import update_dialog

    dns_entered = Event()
    release_dns = Event()
    late_call_done = Event()

    def blocking_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        dns_entered.set()
        assert release_dns.wait(2.0)
        return []

    def dns_blocked_fetch(
        _version: str, *, cancel_event: UpdateCancellation
    ) -> ReleaseInfo | None:
        del cancel_event
        try:
            socket.getaddrinfo("github.com", 443)
            return None
        finally:
            late_call_done.set()

    monkeypatch.setattr(socket, "getaddrinfo", blocking_getaddrinfo)
    monkeypatch.setattr(update_dialog, "fetch_latest_release", dns_blocked_fetch)
    worker = update_dialog.UpdateCheckWorker("0.2.0")
    emitted: list[str] = []
    worker.signals.available.connect(lambda _release: emitted.append("available"))
    worker.signals.no_update.connect(lambda: emitted.append("none"))
    worker.signals.failed.connect(lambda _message: emitted.append("failed"))
    runnable = Thread(target=worker.run, daemon=True)
    runnable.start()

    try:
        assert dns_entered.wait(1.0)
        started = monotonic()
        worker.cancel()
        runnable.join(0.5)
        elapsed = monotonic() - started

        assert not runnable.is_alive()
        assert elapsed < 0.5
        assert emitted == []
    finally:
        release_dns.set()
        runnable.join(1.0)

    assert late_call_done.wait(1.0)
    assert emitted == []


def test_update_download_worker_abandons_blocked_dns_after_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from formulasnip.ui import update_dialog

    dns_entered = Event()
    release_dns = Event()
    late_call_done = Event()

    def blocking_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        dns_entered.set()
        assert release_dns.wait(2.0)
        return []

    def dns_blocked_download(
        asset: UpdateAsset,
        cache_directory: Path,
        *,
        progress: Any,
        phase: Any,
        cancel_event: UpdateCancellation,
    ) -> Path:
        del phase, cancel_event
        try:
            socket.getaddrinfo("github.com", 443)
            progress(asset.size, asset.size)
            return cache_directory / asset.name
        finally:
            late_call_done.set()

    monkeypatch.setattr(socket, "getaddrinfo", blocking_getaddrinfo)
    monkeypatch.setattr(update_dialog, "download_installer", dns_blocked_download)
    asset = UpdateAsset(
        "FormulaSnip-v0.3.0-windows-x64-setup.exe",
        "https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/"
        "FormulaSnip-v0.3.0-windows-x64-setup.exe",
        1,
        "0" * 64,
    )
    release = ReleaseInfo("0.3.0", "v0.3.0", "changes", asset)
    worker = update_dialog.UpdateDownloadWorker(release, tmp_path)
    emitted: list[str] = []
    direct = Qt.ConnectionType.DirectConnection
    worker.signals.progress.connect(
        lambda _received, _total: emitted.append("progress"), type=direct
    )
    worker.signals.finished.connect(
        lambda _path, _release: emitted.append("finished"), type=direct
    )
    worker.signals.failed.connect(
        lambda _message: emitted.append("failed"), type=direct
    )
    runnable = Thread(target=worker.run, daemon=True)
    runnable.start()

    try:
        assert dns_entered.wait(1.0)
        started = monotonic()
        worker.cancel()
        runnable.join(0.5)
        elapsed = monotonic() - started

        assert not runnable.is_alive()
        assert elapsed < 0.5
        assert emitted == []
        assert worker.completed_path is None
    finally:
        release_dns.set()
        runnable.join(1.0)

    assert late_call_done.wait(1.0)
    assert emitted == []
    assert worker.completed_path is None


def test_cancelled_download_retry_waits_for_single_background_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from formulasnip.ui import update_dialog

    first_started = Event()
    release_first = Event()
    first_finished = Event()
    calls: list[Path] = []
    released_paths: list[Path] = []
    asset = UpdateAsset(
        "FormulaSnip-v0.3.0-windows-x64-setup.exe",
        "https://example.invalid/setup.exe",
        1,
        "0" * 64,
    )
    release = ReleaseInfo("0.3.0", "v0.3.0", "changes", asset)

    def blocked_download(
        _asset: UpdateAsset,
        cache_directory: Path,
        **_kwargs: Any,
    ) -> Path:
        calls.append(cache_directory)
        first_started.set()
        assert release_first.wait(2.0)
        first_finished.set()
        return cache_directory / asset.name

    monkeypatch.setattr(update_dialog, "download_installer", blocked_download)
    monkeypatch.setattr(
        update_dialog,
        "release_verified_installer",
        lambda path: released_paths.append(Path(path)),
    )
    first = update_dialog.UpdateDownloadWorker(release, tmp_path / "first")
    second = update_dialog.UpdateDownloadWorker(release, tmp_path / "second")
    first_thread = Thread(target=first.run, daemon=True)
    second_thread = Thread(target=second.run, daemon=True)
    first_thread.start()
    assert first_started.wait(1.0)
    first.cancel()
    first_thread.join(0.5)
    assert not first_thread.is_alive()

    second_thread.start()
    assert not first_finished.wait(0.1)
    assert calls == [tmp_path / "first"]
    second.cancel()
    second_thread.join(0.5)
    assert not second_thread.is_alive()
    assert calls == [tmp_path / "first"]

    release_first.set()
    assert first_finished.wait(1.0)
    assert released_paths == [tmp_path / "first" / asset.name]


def test_update_download_worker_falls_back_to_full_and_reports_actual_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from formulasnip.ui import update_dialog

    lightweight = UpdateAsset(
        "FormulaSnip-v0.3.0-windows-x64-update.exe",
        "https://example.invalid/update.exe",
        1,
        "1" * 64,
    )
    full = UpdateAsset(
        "FormulaSnip-v0.3.0-windows-x64-setup.exe",
        "https://example.invalid/setup.exe",
        2,
        "2" * 64,
    )
    release = ReleaseInfo("0.3.0", "v0.3.0", "changes", lightweight, full)
    full_path = tmp_path / full.name
    calls: list[UpdateAsset] = []

    def fake_download(
        asset: UpdateAsset,
        _cache_directory: Path,
        **_kwargs: Any,
    ) -> Path:
        calls.append(asset)
        if asset is lightweight:
            raise UpdateError("lightweight verification failed")
        return full_path

    monkeypatch.setattr(update_dialog, "download_installer", fake_download)
    worker = update_dialog.UpdateDownloadWorker(release, tmp_path)
    finished: list[tuple[Path, ReleaseInfo]] = []
    progress: list[tuple[int, int]] = []
    worker.signals.progress.connect(
        lambda received, total: progress.append((received, total)),
        type=Qt.ConnectionType.DirectConnection,
    )
    worker.signals.finished.connect(
        lambda path, selected: finished.append((Path(path), selected)),
        type=Qt.ConnectionType.DirectConnection,
    )

    worker.run()

    assert calls == [lightweight, full]
    assert progress == [(0, full.size)]
    assert len(finished) == 1
    assert finished[0][0] == full_path
    assert finished[0][1].asset == full
    assert finished[0][1].fallback_asset is None
    assert worker.completed_release == finished[0][1]


def test_cached_installer_size_and_hash_are_both_checked(tmp_path: Path) -> None:
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    path = tmp_path / name
    path.write_bytes(b"wrong")
    asset = UpdateAsset(name, "https://example.invalid", 5, "0" * 64)
    with pytest.raises(UpdateError, match="SHA-256"):
        verify_installer(path, asset)


def test_installer_replaced_during_hash_is_rejected_and_not_launchable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"trusted"
    replacement = b"hostile"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    original_hash = update_module._sha256_file

    def replace_during_hash(target: Path, cancel_event: object = None) -> str:
        digest = original_hash(target, cancel_event)  # type: ignore[arg-type]
        replacement_path = target.with_suffix(".replacement")
        replacement_path.write_bytes(replacement)
        replacement_path.replace(target)
        return digest

    monkeypatch.setattr(update_module, "_sha256_file", replace_during_hash)
    with pytest.raises(UpdateError, match="changed during verification"):
        verify_installer(path, asset)

    started: list[Path] = []
    with pytest.raises(UpdateError):
        launch_verified_installer(
            path,
            asset,
            start_detached=lambda program, _arguments: started.append(Path(program)) or True,
        )
    assert started == []
    asset = UpdateAsset(name, "https://example.invalid", 10, "0" * 64)
    with pytest.raises(UpdateError, match="size"):
        verify_installer(path, asset)


def test_update_check_throttle_and_manual_bypass() -> None:
    now = 100_000
    assert not should_check_for_updates(now - 60, now_seconds=now)
    assert should_check_for_updates(now - 12 * 60 * 60, now_seconds=now)
    assert should_check_for_updates(now - 60, now_seconds=now, manual=True)
    assert should_check_for_updates("invalid", now_seconds=now)


def test_only_registered_frozen_executable_is_treated_as_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import formulasnip.update as update_module

    installed_executable = tmp_path / "FormulaSnip.exe"
    installed_executable.touch()
    monkeypatch.setattr(update_module.sys, "platform", "win32")
    monkeypatch.setattr(update_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(update_module.sys, "executable", str(installed_executable))
    monkeypatch.setattr(
        update_module, "_registered_install_directory", lambda: tmp_path
    )
    assert is_installed_build()

    monkeypatch.setattr(update_module.sys, "executable", str(tmp_path / "portable.exe"))
    assert not is_installed_build()


def test_installer_launch_revalidates_and_uses_only_fixed_arguments(tmp_path: Path) -> None:
    content = b"setup"
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    calls: list[tuple[str, list[str]]] = []

    assert launch_verified_installer(
        path,
        asset,
        start_detached=lambda program, arguments: calls.append((program, arguments)) or True,
    )
    assert calls == [(str(path), list(INSTALLER_ARGUMENTS))]
    assert "/AUTOUPDATE=1" in calls[0][1]
    assert "/SILENT" in calls[0][1]
    assert "/VERYSILENT" not in calls[0][1]


def test_installer_launch_reuses_background_final_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"setup"
    name = "FormulaSnip-v0.3.0-windows-x64-update.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    verify_installer(path, asset, retain_lock=True)
    monkeypatch.setattr(
        update_module,
        "_sha256_file",
        lambda *_args: pytest.fail("GUI launch must not rescan a verified installer"),
    )

    assert launch_verified_installer(
        path,
        asset,
        start_detached=lambda _program, _arguments: True,
    )


def test_release_verified_installer_is_public_and_idempotent(tmp_path: Path) -> None:
    content = b"setup"
    path = tmp_path / "FormulaSnip-v0.3.0-windows-x64-update.exe"
    path.write_bytes(content)
    asset = UpdateAsset(
        path.name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    verify_installer(path, asset, retain_lock=True)
    key = update_module._installer_cache_key(path)
    assert key in update_module._VERIFIED_INSTALLERS

    release_verified_installer(path)
    release_verified_installer(path)

    assert key not in update_module._VERIFIED_INSTALLERS
    assert key not in update_module._VERIFIED_INSTALLER_HANDLES


def test_retained_installer_verification_denies_same_size_overwrite_until_launch(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows deny-write handle")
    content = b"trusted"
    replacement = b"hostile"
    name = "FormulaSnip-v0.3.0-windows-x64-update.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    verify_installer(path, asset, retain_lock=True)
    with pytest.raises(PermissionError):
        path.write_bytes(replacement)
    seen: list[bytes] = []
    assert launch_verified_installer(
        path,
        asset,
        start_detached=lambda program, _arguments: seen.append(
            Path(program).read_bytes()
        ) or True,
    )
    assert seen == [content]
    path.write_bytes(replacement)
    assert path.read_bytes() == replacement


def test_unexpected_hash_failure_releases_unowned_installer_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"setup"
    name = "FormulaSnip-v0.3.0-windows-x64-update.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    closed: list[int | None] = []
    monkeypatch.setattr(update_module, "_open_installer_read_lock", lambda _path: 123)
    monkeypatch.setattr(update_module, "_close_installer_read_lock", closed.append)
    monkeypatch.setattr(
        update_module,
        "_sha256_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("injected")),
    )

    with pytest.raises(MemoryError, match="injected"):
        verify_installer(path, asset, retain_lock=True)

    assert closed[-1] == 123
    assert closed.count(123) == 1
    assert update_module._installer_cache_key(path) not in update_module._VERIFIED_INSTALLERS
    assert (
        update_module._installer_cache_key(path)
        not in update_module._VERIFIED_INSTALLER_HANDLES
    )
    path.write_bytes(b"retry")


def test_windows_hash_memory_error_releases_real_installer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows deny-write handle")
    content = b"setup"
    name = "FormulaSnip-v0.3.0-windows-x64-update.exe"
    path = tmp_path / name
    path.write_bytes(content)
    asset = UpdateAsset(
        name,
        "https://example.invalid",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    monkeypatch.setattr(
        update_module,
        "_sha256_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MemoryError("injected")),
    )

    with pytest.raises(MemoryError, match="injected"):
        verify_installer(path, asset, retain_lock=True)

    path.write_bytes(b"retry")
    assert path.read_bytes() == b"retry"


def test_inno_autoupdate_restart_and_metadata_cleanup_are_narrow() -> None:
    script = (Path(__file__).parents[1] / "installer" / "FormulaSnip.iss").read_text(
        encoding="utf-8"
    )
    assert "{param:AUTOUPDATE|0}" in script
    assert "Check: IsAutoUpdate" in script
    assert "Check: not IsAutoUpdate" in script
    restart_line = next(line for line in script.splitlines() if "Check: IsAutoUpdate" in line)
    assert "Flags: nowait;" in restart_line
    assert "runhidden" not in restart_line
    assert 'Parameters: "--after-update"' in restart_line
    assert 'Name: "{app}\\_internal\\formulasnip-*.dist-info"' in script
