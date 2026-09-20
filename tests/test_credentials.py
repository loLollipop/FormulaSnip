from __future__ import annotations

import pytest

from formulasnip.credentials import (
    CredentialError,
    OpenAIApiKeyStore,
    validate_openai_api_key,
)


def test_api_key_validation_accepts_openai_and_compatible_provider_keys() -> None:
    project_key = "sk-proj-" + "x" * 32
    service_key = "sk-svcacct-" + "y" * 32
    compatible_key = "provider-token-123"

    assert validate_openai_api_key(f"  {project_key}  ") == project_key
    assert validate_openai_api_key(service_key) == service_key
    assert validate_openai_api_key(compatible_key) == compatible_key


@pytest.mark.parametrize(
    "value",
    (
        "",
        "short",
        "sk-invalid whitespace value",
        "sk-invalid-\nvalue",
    ),
)
def test_api_key_validation_rejects_invalid_values_without_echoing_them(
    value: str,
) -> None:
    with pytest.raises(CredentialError) as captured:
        validate_openai_api_key(value)

    assert str(captured.value) == "API Key 格式无效。"
    if value:
        assert value not in str(captured.value)


class MemoryApiKeyStore(OpenAIApiKeyStore):
    def __init__(self, blob: bytes | None = None) -> None:
        self.blob = blob

    def _read_blob(self) -> bytes | None:
        return self.blob

    def _write_blob(self, blob: bytes) -> None:
        self.blob = blob


def test_api_key_store_binds_key_to_normalized_base_url() -> None:
    store = MemoryApiKeyStore()

    store.save("provider-token-123", "HTTPS://Gateway.Example/v1/")

    assert store.load_for_base_url("https://Gateway.Example/v1") == "provider-token-123"
    assert store.load_for_base_url("https://other.example/v1") is None


def test_api_key_store_treats_legacy_unbound_key_as_absent() -> None:
    store = MemoryApiKeyStore(b"legacy-token-123")

    assert store.load() is None
    assert store.load_for_base_url("https://gateway.example/v1") is None


def test_api_key_store_rejects_invalid_base_url_before_writing() -> None:
    store = MemoryApiKeyStore()

    with pytest.raises(CredentialError, match="地址"):
        store.save("provider-token-123", "")

    assert store.blob is None
