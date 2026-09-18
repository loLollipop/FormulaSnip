"""Store user-provided API credentials outside ordinary application settings."""

from __future__ import annotations

import sys
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_ubyte,
    c_void_p,
    cast,
    create_string_buffer,
    wintypes,
)

OPENAI_CREDENTIAL_TARGET = "FormulaSnip/CompatibleAI"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_MAX_CREDENTIAL_BYTES = 2560


class CredentialError(RuntimeError):
    """The system credential store could not complete an operation."""


class _Credential(Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", POINTER(c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def validate_openai_api_key(value: str) -> str:
    key = value.strip()
    if not 8 <= len(key) <= 512:
        raise CredentialError("API Key 格式无效。")
    if any(character.isspace() or ord(character) < 33 or ord(character) > 126 for character in key):
        raise CredentialError("API Key 格式无效。")
    return key


class OpenAIApiKeyStore:
    """Windows Credential Manager wrapper for an OpenAI-compatible API key."""

    def load(self) -> str | None:
        advapi32 = self._advapi32()
        credential_pointer = POINTER(_Credential)()
        if not advapi32.CredReadW(
            OPENAI_CREDENTIAL_TARGET,
            _CRED_TYPE_GENERIC,
            0,
            byref(credential_pointer),
        ):
            error = self._last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise CredentialError("无法读取 Windows 中保存的 API Key。")
        try:
            credential = credential_pointer.contents
            blob = bytes(
                credential.CredentialBlob[index]
                for index in range(credential.CredentialBlobSize)
            )
            try:
                return validate_openai_api_key(blob.decode("utf-8"))
            except (UnicodeDecodeError, CredentialError) as exc:
                raise CredentialError("Windows 中保存的 API Key 无效，请重新配置。") from exc
        finally:
            advapi32.CredFree(credential_pointer)

    def has_key(self) -> bool:
        return self.load() is not None

    def save(self, value: str) -> None:
        key = validate_openai_api_key(value)
        blob = key.encode("utf-8")
        if len(blob) > _MAX_CREDENTIAL_BYTES:
            raise CredentialError("API Key 过长。")
        buffer = create_string_buffer(blob)
        credential = _Credential()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = OPENAI_CREDENTIAL_TARGET
        credential.Comment = "FormulaSnip optional compatible AI formula correction"
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = cast(buffer, POINTER(c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "FormulaSnip"
        if not self._advapi32().CredWriteW(byref(credential), 0):
            raise CredentialError("无法将 API Key 保存到 Windows 凭据管理器。")

    def delete(self) -> None:
        if self._advapi32().CredDeleteW(
            OPENAI_CREDENTIAL_TARGET,
            _CRED_TYPE_GENERIC,
            0,
        ):
            return
        error = self._last_error()
        if error != _ERROR_NOT_FOUND:
            raise CredentialError("无法从 Windows 凭据管理器删除 API Key。")

    @staticmethod
    def _last_error() -> int:
        from ctypes import get_last_error

        return get_last_error()

    @staticmethod
    def _advapi32():
        if sys.platform != "win32":
            raise CredentialError("API Key 安全存储目前仅支持 Windows。")
        from ctypes import WinDLL

        library = WinDLL("Advapi32.dll", use_last_error=True)
        library.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            POINTER(POINTER(_Credential)),
        ]
        library.CredReadW.restype = wintypes.BOOL
        library.CredWriteW.argtypes = [POINTER(_Credential), wintypes.DWORD]
        library.CredWriteW.restype = wintypes.BOOL
        library.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        library.CredDeleteW.restype = wintypes.BOOL
        library.CredFree.argtypes = [c_void_p]
        library.CredFree.restype = None
        return library
