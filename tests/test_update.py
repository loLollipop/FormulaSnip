from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import requests

from formulasnip.update import (
    INSTALLER_ARGUMENTS,
    LATEST_RELEASE_API,
    LATEST_RELEASE_MANIFEST,
    MAX_MANIFEST_BYTES,
    REQUEST_TIMEOUT,
    ReleaseInfo,
    UpdateAsset,
    UpdateError,
    _fetch_release_manifest,
    download_installer,
    fetch_latest_release,
    is_installed_build,
    is_newer_version,
    launch_verified_installer,
    parse_manifest,
    parse_release,
    parse_version,
    should_check_for_updates,
    validate_asset_url,
    verify_installer,
)

MANIFEST_NAME = "FormulaSnip-update.json"


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
    body = json.dumps(_manifest() if payload is None else payload).encode()
    return [
        _Response(url=LATEST_RELEASE_MANIFEST, status_code=302, location=tagged_url),
        _Response(url=tagged_url, status_code=302, location=asset_url),
        _Response(
            content=body,
            url=asset_url,
            content_length=len(body),
        ),
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
        self._content = content
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


def test_static_manifest_success_does_not_call_release_api() -> None:
    client = _Client(_manifest_responses())
    release = fetch_latest_release("0.2.0", client=client)
    assert release is not None
    assert len(client.calls) == 3
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
    api_response = _Response(payload=_payload(), url=LATEST_RELEASE_API)
    client = _Client([static_failure, api_response])

    release = fetch_latest_release("0.2.0", client=client)

    assert release is not None
    assert release.version == "0.3.0"
    assert [url for url, _ in client.calls] == [LATEST_RELEASE_MANIFEST, LATEST_RELEASE_API]
    assert static_failure.closed
    assert api_response.closed


def test_both_update_channels_fail_with_friendly_error() -> None:
    static_failure = _Response(url=LATEST_RELEASE_MANIFEST, status_code=404)
    api_failure = _Response(url=LATEST_RELEASE_API, status_code=403)
    client = _Client([static_failure, api_failure])

    with pytest.raises(UpdateError, match="无法检查更新"):
        fetch_latest_release("0.2.0", client=client)

    assert len(client.calls) == 2
    assert static_failure.closed
    assert api_failure.closed


def test_download_streams_verifies_and_atomically_renames(tmp_path: Path) -> None:
    content = b"trusted installer"
    sha256 = hashlib.sha256(content).hexdigest()
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    url = f"https://github.com/loLollipop/FormulaSnip/releases/download/v0.3.0/{name}"
    asset = UpdateAsset(name, url, len(content), sha256)
    response = _Response(
        content=content,
        url=(
            "https://release-assets.githubusercontent.com/"
            "github-production-release-asset/1/test-asset"
        ),
        content_length=len(content),
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
    assert progress[-1] == (len(content), len(content))
    assert not list(tmp_path.glob("*.part"))
    assert len(client.calls) == 2
    assert all(call[1]["stream"] is True for call in client.calls)
    assert all(call[1]["allow_redirects"] is False for call in client.calls)
    assert client.calls[0][1]["timeout"] == REQUEST_TIMEOUT


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


def test_cached_installer_size_and_hash_are_both_checked(tmp_path: Path) -> None:
    name = "FormulaSnip-v0.3.0-windows-x64-setup.exe"
    path = tmp_path / name
    path.write_bytes(b"wrong")
    asset = UpdateAsset(name, "https://example.invalid", 5, "0" * 64)
    with pytest.raises(UpdateError, match="SHA-256"):
        verify_installer(path, asset)
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
    assert 'Name: "{app}\\_internal\\formulasnip-*.dist-info"' in script
