from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from typing import Any

import pytest
import requests
from PIL import Image

from formulasnip.domain import RecognitionResult
from formulasnip.recognition import openai_correction
from formulasnip.recognition.openai_correction import (
    AICorrectionError,
    enhance_formula,
    list_compatible_models,
    transcribe_formula,
    validate_ai_base_url,
)
from formulasnip.recognition.openai_correction import (
    test_compatible_model_access as check_model_access,
)

_LOCALHOST_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIC5TCCAc2gAwIBAgIUQZrzH40Qns37dCXiDC9AZE1RU2UwDQYJKoZIhvcNAQEL
BQAwFDESMBAGA1UEAwwJMTI3LjAuMC4xMB4XDTIwMDEwMTAwMDAwMFoXDTQwMDEw
MTAwMDAwMFowFDESMBAGA1UEAwwJMTI3LjAuMC4xMIIBIjANBgkqhkiG9w0BAQEF
AAOCAQ8AMIIBCgKCAQEAuiZ3LEtHr42APNu7YDM0Vjx57B4F+eACvTeHtw9Cr8/E
HkhaWEvRGu5g9COAqF3w7I2M/k92dxCQZFtK9/FlTcFBeqXcKz+GqbpZzIndBNNr
+hldU07dBMqOTjpax9frCXynm+A9ABag6F9TgZir0QXx0JbAzxG0v/bjV/UIptho
/HKqL9Bi9Y9h9wwsmAnZVRD3k8yyVXaROEa6uzE0m/knNfFeWJfdOl1mVDDfneZd
210fYXVOo0SfIhivbXttTn5iJXwlN2rbwg7TicmUmzuzW8Ti8uqH4pCef3LMbNhy
WX5RCovpbXn+vNoyYywXXizePRGJ1mnq/ykonu8CBQIDAQABoy8wLTAaBgNVHREE
EzARhwR/AAABgglsb2NhbGhvc3QwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0B
AQsFAAOCAQEACgkDTAHArFsyOHPd9GLqd/rcfr3qeKGy5gmzCb3H2CCF0YTwXN3+
JDFFbBZRzuHhyWXsNWGu1jrtjt+6hkB+nRA2nzrt4MrDGm0gryLC+Y9BHaUDwJ9K
o0tqlL5YbJHwNsy2YHbZZnoUG4WURw2BQKaQH/ZkRvBDd9GiJ6mJzMJu/ltbtQta
8calIv1mq+g8+x2d7ZkErOemVTib0eTXauodtVzSaL1F11Rc9VIjlk/EuoX47AOv
zLRLeUEMgI6HPlWu8aew5oC+WJkRxIubvXkxSd2CTPIz5WevNJE8DPnNKsNOHpM5
PV6QiOUg9IWTNtLEsD1Iz1HwgY8VeW5KBA==
-----END CERTIFICATE-----
"""
_LOCALHOST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC6JncsS0evjYA8
27tgMzRWPHnsHgX54AK9N4e3D0Kvz8QeSFpYS9Ea7mD0I4CoXfDsjYz+T3Z3EJBk
W0r38WVNwUF6pdwrP4apulnMid0E02v6GV1TTt0Eyo5OOlrH1+sJfKeb4D0AFqDo
X1OBmKvRBfHQlsDPEbS/9uNX9Qim2Gj8cqov0GL1j2H3DCyYCdlVEPeTzLJVdpE4
Rrq7MTSb+Sc18V5Yl906XWZUMN+d5l3bXR9hdU6jRJ8iGK9te21OfmIlfCU3atvC
DtOJyZSbO7NbxOLy6ofikJ5/csxs2HJZflEKi+ltef682jJjLBdeLN49EYnWaer/
KSie7wIFAgMBAAECggEADCWbbDADXwDAR/hcq0PcG+55VD+HS01jUF6RxA/CXb+U
gBdfkdhsrjG08OlqKVJr+Lup4iRkShOyIGJWq4Q8hIziTXMKQWY1TtkCqBas7fYv
2xORo/CG+puPGqqzJsw/oZBZTZId2OYhHNivlcrVF2AobeCQd1Kj9UzSe/hY1q42
3nvgw10mpttmmk3o+ODpgbhRAnAHTmhDWD+hOZ4iWmbqQHhKAQWGBpytsUqk7rRc
Cu8ZPd2iL4E7GklQHMpQnEOp25YsqATBB3BBKBMa9/8SnuAk0s9dZk1koDzn4LCO
3cQZnIfX1PSymRnmLFiBobtipENVRgN3Nj1WHbLToQKBgQDuK98EM/spt8Sc09UM
ml5H4EAp3v5aXPNkGf1C68LeeBmmRXD7jvhnzeWS0G4CuC9v9lrIlDBLTzqhjjj8
Cg8fxe/2gpzEqzT4w4RbAi9kUCsDXOUtMVUpjuL30SH/Iw1nB/0MqE8kE5ofu3QO
Fk382KBfsa7TZ4raIpBpgmOyNQKBgQDIFbPeifNVUPHcxVIqgmQo3pKQLs12Bnxt
Ote7UeD5Wg/kljJ6HXzqWyfcvDiJybYqjBNb+2aXsCRLILv4GpNHbDmmBEQj7QNF
Pw4htcUqv/knmmEt/enC6j5m3DKvM62PDimER1UF9ElvQU1IWjxq5vF9N/gn8NFI
uwqF4Z0KkQKBgHpZ2Thsh7NXr04tWD4gMxzTa8LWxm2fYH1lCIDPYo0sv2h2NeNU
//E7iZsRLeKBwgTPVrXBwsl9Sw5hZI69kCVvZqWJVYWGujCtKBokljn/IQmaODUu
KaSuvZQ3QDK0TBdIuEs/T2CmHT/96VGvTaL9me1u9vOtNlx28x7wl8ydAoGAXIMc
XYLvTb1VdzyNFzae1P7ESYI6YZ3yHhcc9HGRUfnAa3K++BN2VG29aqRkh+EKJ3YI
5XjCINTCkzIZd0fiXR2/MfG7B9lor7XN9Ow0s+V7cEJDOJ60XPktzSV3EecVEpX7
wDuzJkOjSJuq/g8q7ErH0Zv1U5JXUgeZf/mnQOECgYA8u+51Uu/AqkgtdX9eAkbn
cq3UsNb0eP5sFUBxzCE8lkzyM37m36dsR5HNq5N55GJgDB4ivXgQH85/io7u03wS
/cGHH3JZiD67ubTEUOmiIHH/CwLCdcgjOlmrGjLnsyU/fkHBWBKIIg62XcXwfvVU
XWaS2l+tCN7Jv436GUWhMg==
-----END PRIVATE KEY-----
"""


def _chat_payload(latex: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"latex": latex}),
                }
            }
        ]
    }


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError("simulated response failure")

    def json(self) -> object:
        return self._payload

    def iter_content(self, chunk_size: int) -> Any:
        content = json.dumps(self._payload).encode("utf-8")
        for offset in range(0, len(content), chunk_size):
            yield content[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(
        self,
        *,
        post_response: FakeResponse | Exception | None = None,
        get_response: FakeResponse | Exception | None = None,
    ) -> None:
        self.post_response = post_response
        self.get_response = get_response
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        assert self.post_response is not None
        return self.post_response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        if isinstance(self.get_response, Exception):
            raise self.get_response
        assert self.get_response is not None
        return self.get_response


def _local_result(latex: str = "x+y") -> RecognitionResult:
    return RecognitionResult(latex, "MathCraft", 0.25)


def _request_transport_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == "FormulaSnip OpenAI request"
    ]


def _wait_for_request_transport_shutdown(timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while _request_transport_threads() and time.monotonic() < deadline:
        time.sleep(0.01)
    return not _request_transport_threads()


def test_ai_correction_uses_openai_compatible_chat_contract() -> None:
    response = FakeResponse(200, _chat_payload(r"x+\frac{y}{z}"))
    client = FakeClient(post_response=response)

    result = enhance_formula(
        Image.new("RGB", (32, 16), "white"),
        _local_result(),
        "unit-test-token",
        base_url="https://gateway.example/v1/",
        model="vision-model",
        client=client,
    )

    assert result.latex == r"x+\frac{y}{z}"
    assert result.backend_name == "MathCraft + vision-model"
    assert result.strategy == "ai-assisted"
    assert response.closed is True
    assert len(client.post_calls) == 1
    url, request = client.post_calls[0]
    assert url == "https://gateway.example/v1/chat/completions"
    assert request["allow_redirects"] is False
    assert request["headers"]["Authorization"] == "Bearer unit-test-token"
    body = request["json"]
    assert body["model"] == "vision-model"
    assert body["store"] is False
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "x+y" in body["messages"][1]["content"][0]["text"]
    image_input = body["messages"][1]["content"][1]
    assert image_input["type"] == "image_url"
    assert image_input["image_url"]["detail"] == "high"
    assert image_input["image_url"]["url"].startswith("data:image/png;base64,")


def test_direct_ai_transcription_does_not_send_a_local_candidate() -> None:
    response = FakeResponse(200, _chat_payload(r"\frac{x}{y}"))
    client = FakeClient(post_response=response)

    candidate = transcribe_formula(
        Image.new("RGB", (32, 16), "white"),
        "unit-test-token",
        base_url="https://gateway.example/v1/",
        model="vision-model",
        client=client,
    )

    assert candidate.latex == r"\frac{x}{y}"
    assert candidate.backend == "AI · vision-model"
    assert candidate.source == "ai"
    assert candidate.previewable is True
    body = client.post_calls[0][1]["json"]
    prompt = body["messages"][1]["content"][0]["text"]
    assert "Local OCR candidate" not in prompt
    assert body["messages"][0]["content"] != openai_correction._SYSTEM_PROMPT


def test_direct_ai_transcription_rejects_unsafe_latex_without_echoing_key() -> None:
    key = "secret-unit-test-token"
    with pytest.raises(AICorrectionError) as raised:
        transcribe_formula(
            Image.new("RGB", (8, 8), "white"),
            key,
            client=FakeClient(
                post_response=FakeResponse(200, _chat_payload(r"\input{secret}"))
            ),
        )

    assert key not in str(raised.value)
    assert r"\input{secret}" not in str(raised.value)


def test_direct_ai_transcription_retains_valid_nonpreviewable_candidate(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(openai_correction, "is_formula_previewable", lambda _latex: False)

    candidate = transcribe_formula(
        Image.new("RGB", (8, 8), "white"),
        "unit-test-token",
        client=FakeClient(post_response=FakeResponse(200, _chat_payload("x"))),
    )

    assert candidate.latex == "x"
    assert candidate.previewable is False


def test_ai_correction_can_confirm_an_unchanged_result() -> None:
    result = enhance_formula(
        Image.new("RGB", (8, 8), "white"),
        _local_result(),
        "unit-test-token",
        client=FakeClient(post_response=FakeResponse(200, _chat_payload(" x + y "))),
    )

    assert result.latex == "x + y"
    assert result.warnings[-1] == "AI 已核对本地识别结果，请与原图核对。"


def test_ai_correction_checks_cancellation_during_preview_validation(
    monkeypatch: Any,
) -> None:
    cancelled = Event()

    def preview_and_cancel(_latex: str) -> bool:
        cancelled.set()
        return True

    monkeypatch.setattr(openai_correction, "is_formula_previewable", preview_and_cancel)

    with pytest.raises(AICorrectionError, match="已取消"):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=FakeResponse(200, _chat_payload("z"))),
            cancel_event=cancelled,
        )


@pytest.mark.parametrize(
    ("status", "message"),
    (
        (301, "不安全的重定向"),
        (401, "API Key 无效"),
        (403, "无权使用所选模型"),
        (429, "额度不足"),
        (500, "服务暂时不可用"),
        (400, "请求未被接受"),
    ),
)
def test_ai_correction_maps_http_failures_and_closes_response(
    status: int,
    message: str,
) -> None:
    response = FakeResponse(status, {})

    with pytest.raises(AICorrectionError, match=message):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=response),
        )

    assert response.closed is True


def test_ai_correction_maps_timeout_without_exposing_exception_text() -> None:
    marker = "secret-transport-detail"

    with pytest.raises(AICorrectionError) as captured:
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=requests.Timeout(marker)),
        )

    assert "连接失败或超时" in str(captured.value)
    assert marker not in str(captured.value)


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "not-json"}}]},
    ),
)
def test_ai_correction_rejects_invalid_output(payload: object) -> None:
    with pytest.raises(AICorrectionError):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=FakeResponse(200, payload)),
        )


def test_ai_correction_rejects_oversized_latex_before_expensive_processing(
    monkeypatch: Any,
) -> None:
    marker = "untrusted-upstream-output"
    oversized_latex = marker + r"\text{" * 20_000
    response = FakeResponse(200, _chat_payload(oversized_latex))

    def fail_if_called(_latex: str) -> Any:
        pytest.fail("oversized AI LaTeX reached expensive processing")

    monkeypatch.setattr(openai_correction, "normalize_latex", fail_if_called)
    monkeypatch.setattr(openai_correction, "has_fatal_output_issue", fail_if_called)
    monkeypatch.setattr(openai_correction, "assess_latex", fail_if_called)
    monkeypatch.setattr(openai_correction, "is_formula_previewable", fail_if_called)

    started = time.monotonic()
    with pytest.raises(AICorrectionError, match="过长") as captured:
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=response),
        )

    assert time.monotonic() - started < 0.5
    assert "已保留本地结果" in str(captured.value)
    assert marker not in str(captured.value)
    assert response.closed is True


def test_ai_correction_accepts_fenced_json_from_compatible_provider() -> None:
    response = FakeResponse(
        200,
        {"choices": [{"message": {"content": '```json\n{"latex":"x"}\n```'}}]},
    )

    result = enhance_formula(
        Image.new("RGB", (8, 8), "white"),
        _local_result(),
        "unit-test-token",
        client=FakeClient(post_response=response),
    )

    assert result.latex == "x"


def test_ai_correction_rejects_unsafe_latex() -> None:
    with pytest.raises(AICorrectionError, match="安全校验"):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(
                post_response=FakeResponse(200, _chat_payload(r"\input{file}"))
            ),
        )


def test_oversized_image_is_rejected_before_request(monkeypatch: Any) -> None:
    client = FakeClient(post_response=FakeResponse(200, _chat_payload("x")))
    monkeypatch.setattr(openai_correction, "MAX_IMAGE_PIXELS", 1)

    with pytest.raises(AICorrectionError, match="截图过大"):
        enhance_formula(
            Image.new("RGB", (2, 2), "white"),
            _local_result(),
            "unit-test-token",
            client=client,
        )

    assert client.post_calls == []


def test_oversized_response_is_rejected_and_closed(monkeypatch: Any) -> None:
    response = FakeResponse(200, _chat_payload("x" * 100))
    client = FakeClient(post_response=response)
    monkeypatch.setattr(openai_correction, "MAX_RESPONSE_BYTES", 32)

    with pytest.raises(AICorrectionError, match="响应过大"):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=client,
        )

    assert response.closed is True


def test_slow_drip_response_respects_total_deadline(monkeypatch: Any) -> None:
    class SlowResponse(FakeResponse):
        def iter_content(self, chunk_size: int) -> Any:
            del chunk_size
            content = json.dumps(_chat_payload("x")).encode("utf-8")
            for byte in content:
                time.sleep(0.003)
                yield bytes((byte,))

    response = SlowResponse(200, _chat_payload("x"))
    monkeypatch.setattr(openai_correction, "AI_TOTAL_TIMEOUT_SECONDS", 0.02)

    with pytest.raises(AICorrectionError, match="总时限"):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=FakeClient(post_response=response),
        )

    assert response.closed is True


@pytest.mark.parametrize(
    ("cancel_during_request", "message"),
    ((True, "已取消"), (False, "总时限")),
)
def test_abort_race_preserves_original_control_flow_error(
    cancel_during_request: bool,
    message: str,
    monkeypatch: Any,
) -> None:
    cancelled = Event()
    stream_started = Event()
    release_stream = Event()

    class Raw:
        def shutdown(self) -> None:
            raise ValueError("I/O operation on closed response")

    class ConcurrentCloseResponse(FakeResponse):
        def __init__(self) -> None:
            super().__init__(200, {"data": [{"id": "local-vision"}]})
            self.raw = Raw()
            self.close_count = 0

        def iter_content(self, chunk_size: int) -> Any:
            del chunk_size
            stream_started.set()
            release_stream.wait(1)
            yield b""

        def close(self) -> None:
            self.close_count += 1
            self.closed = True
            release_stream.set()

    response = ConcurrentCloseResponse()

    def abort_after_transfer_close(_tracker: Any) -> None:
        response.close()

    monkeypatch.setattr(
        openai_correction._ConnectionTracker,
        "abort",
        abort_after_transfer_close,
    )
    monkeypatch.setattr(openai_correction, "AI_TOTAL_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(openai_correction, "AI_CANCEL_POLL_SECONDS", 0.002)

    canceller: threading.Thread | None = None
    if cancel_during_request:
        def cancel_after_stream_starts() -> None:
            if stream_started.wait(1):
                cancelled.set()

        canceller = threading.Thread(target=cancel_after_stream_starts, daemon=True)
        canceller.start()

    with pytest.raises(AICorrectionError, match=message):
        list_compatible_models(
            "unit-test-token",
            "https://gateway.example/v1",
            client=FakeClient(get_response=response),
            cancel_event=cancelled,
        )

    if canceller is not None:
        canceller.join(timeout=1)
    assert response.close_count >= 2
    assert _wait_for_request_transport_shutdown()


@pytest.mark.parametrize(
    ("cancel_during_request", "message"),
    ((True, "已取消"), (False, "总时限")),
)
def test_repeated_aborts_leave_no_request_transport_thread(
    cancel_during_request: bool,
    message: str,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(openai_correction, "AI_TOTAL_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(openai_correction, "AI_CANCEL_POLL_SECONDS", 0.002)

    for _attempt in range(3):
        cancelled = Event()
        stream_started = Event()
        release_stream = Event()

        class DelayedAbortResponse(FakeResponse):
            def __init__(self, stream_started: Event, release_stream: Event) -> None:
                super().__init__(200, {"data": [{"id": "local-vision"}]})
                self._stream_started = stream_started
                self._release_stream = release_stream

            def iter_content(self, chunk_size: int) -> Any:
                del chunk_size
                self._stream_started.set()
                self._release_stream.wait(1)
                time.sleep(0.03)
                yield b""

            def close(self) -> None:
                self.closed = True
                self._release_stream.set()

        response = DelayedAbortResponse(stream_started, release_stream)

        canceller: threading.Thread | None = None
        if cancel_during_request:

            def cancel_after_stream_starts(
                start_event: Event,
                cancel_signal: Event,
            ) -> None:
                if start_event.wait(1):
                    cancel_signal.set()

            canceller = threading.Thread(
                target=cancel_after_stream_starts,
                args=(stream_started, cancelled),
                daemon=True,
            )
            canceller.start()

        with pytest.raises(AICorrectionError, match=message):
            list_compatible_models(
                "unit-test-token",
                "https://gateway.example/v1",
                client=FakeClient(get_response=response),
                cancel_event=cancelled,
            )

        if canceller is not None:
            canceller.join(timeout=1)
        assert not _request_transport_threads()


def test_cancel_closes_owned_session_with_bounded_wait(
    monkeypatch: Any,
) -> None:
    cancelled = Event()
    request_started = Event()
    release_request = Event()
    session_closed = Event()

    class UncooperativeOwnedSession:
        def mount(self, _prefix: str, _adapter: Any) -> None:
            pass

        def get(self, _url: str, **_kwargs: Any) -> FakeResponse:
            request_started.set()
            release_request.wait(1)
            return FakeResponse(200, {"data": [{"id": "local-vision"}]})

        def close(self) -> None:
            session_closed.set()

    monkeypatch.setattr(openai_correction, "AI_CANCEL_POLL_SECONDS", 0.002)
    monkeypatch.setattr(openai_correction, "AI_REQUEST_CLEANUP_SECONDS", 0.03)
    monkeypatch.setattr(
        openai_correction.requests,
        "Session",
        UncooperativeOwnedSession,
    )

    def cancel_after_request_starts() -> None:
        if request_started.wait(1):
            cancelled.set()

    canceller = threading.Thread(target=cancel_after_request_starts, daemon=True)
    canceller.start()
    started = time.monotonic()
    try:
        with pytest.raises(AICorrectionError, match="已取消"):
            list_compatible_models(
                "unit-test-token",
                "https://gateway.example/v1",
                cancel_event=cancelled,
            )
        assert time.monotonic() - started < 0.20
        assert session_closed.is_set()
    finally:
        release_request.set()
        canceller.join(timeout=1)
        assert _wait_for_request_transport_shutdown()


def test_real_slow_drip_body_is_aborted_at_total_deadline(monkeypatch: Any) -> None:
    response_started = Event()
    client_disconnected = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            content = json.dumps({"data": [{"id": "local-vision"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            response_started.set()
            for byte in content:
                try:
                    self.wfile.write(bytes((byte,)))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    client_disconnected.set()
                    return
                time.sleep(0.02)

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(openai_correction, "AI_TOTAL_TIMEOUT_SECONDS", 0.10)
    started = time.monotonic()
    try:
        with pytest.raises(AICorrectionError, match="总时限"):
            list_compatible_models(
                "unit-test-token",
                f"http://127.0.0.1:{server.server_port}/v1",
            )
        elapsed = time.monotonic() - started
        assert response_started.is_set()
        assert elapsed < 0.30
        assert client_disconnected.wait(0.50)
        assert _wait_for_request_transport_shutdown()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_running_request_can_cancel_while_waiting_for_response_headers(
    monkeypatch: Any,
) -> None:
    request_received = Event()
    client_disconnected = Event()
    cancelled = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_received.set()
            self.connection.settimeout(0.05)
            while True:
                try:
                    if self.connection.recv(1) == b"":
                        client_disconnected.set()
                        return
                except TimeoutError:
                    continue
                except (ConnectionAbortedError, ConnectionResetError, OSError):
                    client_disconnected.set()
                    return

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(openai_correction, "AI_TIMEOUT", (0.5, 0.5))

    def cancel_after_request_arrives() -> None:
        if request_received.wait(1):
            time.sleep(0.05)
            cancelled.set()

    canceller = threading.Thread(target=cancel_after_request_arrives, daemon=True)
    canceller.start()
    started = time.monotonic()
    try:
        with pytest.raises(AICorrectionError, match="已取消"):
            list_compatible_models(
                "unit-test-token",
                f"http://127.0.0.1:{server.server_port}/v1",
                cancel_event=cancelled,
            )
        elapsed = time.monotonic() - started
        assert elapsed < 0.30
        assert client_disconnected.wait(0.50)
        assert _wait_for_request_transport_shutdown()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        canceller.join(timeout=2)


def test_https_deadline_aborts_connection_during_tls_handshake(
    monkeypatch: Any,
) -> None:
    connection_accepted = Event()
    client_disconnected = Event()
    listening = socket.socket()
    listening.bind(("127.0.0.1", 0))
    listening.listen()
    port = listening.getsockname()[1]

    def hold_tls_handshake() -> None:
        connection, _address = listening.accept()
        connection_accepted.set()
        connection.settimeout(0.05)
        try:
            while True:
                try:
                    if connection.recv(4096) == b"":
                        client_disconnected.set()
                        return
                except TimeoutError:
                    continue
                except (ConnectionAbortedError, ConnectionResetError, OSError):
                    client_disconnected.set()
                    return
        finally:
            connection.close()

    server_thread = threading.Thread(target=hold_tls_handshake, daemon=True)
    server_thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(openai_correction, "AI_TOTAL_TIMEOUT_SECONDS", 0.10)
    monkeypatch.setattr(openai_correction, "AI_TIMEOUT", (1.0, 1.0))
    started = time.monotonic()
    try:
        with pytest.raises(AICorrectionError, match="总时限"):
            list_compatible_models(
                "unit-test-token",
                f"https://127.0.0.1:{port}/v1",
            )
        assert connection_accepted.is_set()
        assert time.monotonic() - started < 0.30
        assert client_disconnected.wait(0.50)
        assert _wait_for_request_transport_shutdown()
    finally:
        listening.close()
        server_thread.join(timeout=2)


def test_https_running_request_cancel_aborts_slow_response_headers(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    certificate = tmp_path / "localhost.pem"
    private_key = tmp_path / "localhost-key.pem"
    certificate.write_text(_LOCALHOST_CERTIFICATE, encoding="ascii")
    private_key.write_text(_LOCALHOST_PRIVATE_KEY, encoding="ascii")
    request_received = Event()
    client_disconnected = Event()
    cancelled = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request_received.set()
            self.connection.settimeout(0.05)
            while True:
                try:
                    if self.connection.recv(1) == b"":
                        client_disconnected.set()
                        return
                except TimeoutError:
                    continue
                except (ConnectionAbortedError, ConnectionResetError, OSError):
                    client_disconnected.set()
                    return

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(certificate))
    monkeypatch.setattr(openai_correction, "AI_TIMEOUT", (1.0, 1.0))

    def cancel_after_request_arrives() -> None:
        if request_received.wait(1):
            cancelled.set()

    canceller = threading.Thread(target=cancel_after_request_arrives, daemon=True)
    canceller.start()
    started = time.monotonic()
    try:
        with pytest.raises(AICorrectionError, match="已取消"):
            list_compatible_models(
                "unit-test-token",
                f"https://127.0.0.1:{server.server_port}/v1",
                cancel_event=cancelled,
            )
        assert time.monotonic() - started < 0.30
        assert client_disconnected.wait(0.50)
        assert _wait_for_request_transport_shutdown()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        canceller.join(timeout=2)


def test_response_is_closed_when_stream_read_fails() -> None:
    class BrokenResponse(FakeResponse):
        def iter_content(self, chunk_size: int) -> Any:
            del chunk_size
            raise requests.ConnectionError("simulated stream failure")
            yield b""  # pragma: no cover

    response = BrokenResponse(200, {})

    with pytest.raises(AICorrectionError, match="无法连接"):
        list_compatible_models(
            "unit-test-token",
            "https://gateway.example/v1",
            client=FakeClient(get_response=response),
        )

    assert response.closed is True


def test_cancelled_request_does_not_reach_client() -> None:
    cancelled = Event()
    cancelled.set()
    client = FakeClient(post_response=FakeResponse(200, _chat_payload("x")))

    with pytest.raises(AICorrectionError, match="已取消"):
        enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            client=client,
            cancel_event=cancelled,
        )

    assert client.post_calls == []


def test_model_list_is_loaded_from_configured_upstream_and_sorted() -> None:
    response = FakeResponse(
        200,
        {
            "data": [
                {"id": "vision-z"},
                {"id": "gpt-5.6-luna"},
                {"id": "vision-a"},
                {"not-id": "ignored"},
            ]
        },
    )
    client = FakeClient(get_response=response)

    models = list_compatible_models(
        "unit-test-token",
        "https://gateway.example/v1",
        client=client,
    )

    assert models == ("gpt-5.6-luna", "vision-a", "vision-z")
    assert client.get_calls[0][0] == "https://gateway.example/v1/models"
    assert response.closed is True


def test_loopback_http_model_request_ignores_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_requests: list[str | None] = []
    proxy_requests: list[str] = []

    class LocalHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            local_requests.append(self.headers.get("Authorization"))
            content = json.dumps({"data": [{"id": "local-vision"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            proxy_requests.append(self.path)
            content = json.dumps({"data": [{"id": "proxy-intercepted"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    local_server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    local_server.daemon_threads = True
    proxy_server.daemon_threads = True
    local_thread = threading.Thread(target=local_server.serve_forever, daemon=True)
    proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    local_thread.start()
    proxy_thread.start()
    proxy_url = f"http://127.0.0.1:{proxy_server.server_port}"
    for variable in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(variable, proxy_url)
    for variable in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(variable, "")

    try:
        models = list_compatible_models(
            "loopback-secret-token",
            f"http://127.0.0.1:{local_server.server_port}/v1",
        )
    finally:
        local_server.shutdown()
        proxy_server.shutdown()
        local_server.server_close()
        proxy_server.server_close()
        local_thread.join(timeout=2)
        proxy_thread.join(timeout=2)

    assert models == ("local-vision",)
    assert local_requests == ["Bearer loopback-secret-token"]
    assert proxy_requests == []


def test_model_access_check_runs_tiny_multimodal_request() -> None:
    client = FakeClient(
        post_response=FakeResponse(200, _chat_payload("x"))
    )

    assert (
        check_model_access(
            "unit-test-token",
            "https://gateway.example/v1",
            "vision-model",
            client=client,
        )
        == "vision-model"
    )
    assert client.get_calls == []
    assert client.post_calls[0][0] == "https://gateway.example/v1/chat/completions"
    assert client.post_calls[0][1]["json"]["max_completion_tokens"] == 256


def test_model_access_rejects_oversized_latex_before_normalization(
    monkeypatch: Any,
) -> None:
    marker = "untrusted-model-test-output"
    response = FakeResponse(
        200,
        _chat_payload(marker + "x" * openai_correction.MAX_AI_LATEX_CHARS),
    )

    def fail_if_called(_latex: str) -> Any:
        pytest.fail("oversized model-test LaTeX reached normalization")

    monkeypatch.setattr(openai_correction, "normalize_latex", fail_if_called)

    with pytest.raises(AICorrectionError, match="过长") as captured:
        check_model_access(
            "unit-test-token",
            "https://gateway.example/v1",
            "vision-model",
            client=FakeClient(post_response=response),
        )

    assert marker not in str(captured.value)
    assert response.closed is True


@pytest.mark.parametrize(
    "value",
    (
        "http://remote.example/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?token=secret",
        "not-a-url",
    ),
)
def test_remote_base_url_validation_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(AICorrectionError):
        validate_ai_base_url(value)


def test_local_http_base_url_is_allowed_for_compatible_local_servers() -> None:
    assert (
        validate_ai_base_url("http://127.0.0.1:11434/v1/")
        == "http://127.0.0.1:11434/v1"
    )


def test_real_http_serialization_against_local_compatible_server() -> None:
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            assert self.path == "/v1/models"
            self._send({"data": [{"id": "local-vision"}]})

        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/v1/chat/completions"
            length = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(length))
            received.append(request)
            test_latex = "x" if request["max_completion_tokens"] == 256 else "x+y"
            self._send(_chat_payload(test_latex))

        def _send(self, payload: object) -> None:
            content = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        assert list_compatible_models("unit-test-token", base_url) == (
            "local-vision",
        )
        assert (
            check_model_access(
                "unit-test-token",
                base_url,
                "local-vision",
            )
            == "local-vision"
        )
        result = enhance_formula(
            Image.new("RGB", (8, 8), "white"),
            _local_result(),
            "unit-test-token",
            base_url=base_url,
            model="local-vision",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.latex == "x+y"
    assert len(received) == 2
    assert all(item["model"] == "local-vision" for item in received)
    assert received[1]["messages"][1]["content"][1]["type"] == "image_url"
