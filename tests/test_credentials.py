from __future__ import annotations

import pytest

from formulasnip.credentials import CredentialError, validate_openai_api_key


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
