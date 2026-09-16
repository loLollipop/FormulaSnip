from __future__ import annotations

import multiprocessing
import os
from collections import deque
from multiprocessing.shared_memory import SharedMemory
from threading import Event, Thread
from typing import Any

import pytest
from PIL import Image

from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import RecognitionError
from formulasnip.recognition.paddle_backend import PaddleFormulaBackend
from formulasnip.recognition.paddle_worker import PaddleWorkerClient


class Connection:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = deque(responses)
        self.sent: list[Any] = []
        self.closed = False

    def send(self, message: Any) -> None:
        self.sent.append(message)

    def poll(self, timeout: float) -> bool:
        return bool(self.responses)

    def recv(self) -> Any:
        value = self.responses.popleft()
        if isinstance(value, Exception):
            raise value
        return value

    def close(self) -> None:
        self.closed = True


class Process:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.pid: int | None = None
        self.exitcode: int | None = None
        self.alive = False
        self.closed = False
        self.terminated = False
        self.fail_start = fail_start

    def start(self) -> None:
        if self.fail_start:
            raise OSError("process start failed")
        self.pid = 123
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float) -> None:
        pass

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False
        self.exitcode = -1

    kill = terminate

    def close(self) -> None:
        self.closed = True


class Context:
    def __init__(self, responses: list[list[Any]], *, fail_start: bool = False) -> None:
        self.responses = deque(responses)
        self.parents: list[Connection] = []
        self.children: list[Connection] = []
        self.processes: list[Process] = []
        self.fail_start = fail_start

    def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:  # noqa: N802
        assert duplex
        parent, child = Connection(self.responses.popleft()), Connection([])
        self.parents.append(parent)
        self.children.append(child)
        return parent, child

    def Process(self, **kwargs: Any) -> Process:  # noqa: N802
        assert kwargs["daemon"] is True
        process = Process(fail_start=self.fail_start)
        self.processes.append(process)
        return process


READY = ("ready", 0, None)
RESULT = RecognitionResult("x+y", "Paddle", 0.2)


def test_worker_warmup_and_inference_reuse_one_process_with_unique_ids() -> None:
    context = Context([[READY, ("result", 1, RESULT), ("result", 2, RESULT)]])
    client = PaddleWorkerClient(context=context)
    backend = PaddleFormulaBackend(client=client)
    try:
        backend.warmup()
        backend.warmup()
        assert backend.recognize(Image.new("L", (5, 4))).latex == "x+y"
        assert backend.recognize(Image.new("RGB", (5, 4))).latex == "x+y"
        assert len(context.processes) == 1
        assert [item[1] for item in context.parents[0].sent] == [1, 2]
        assert context.parents[0].sent[0][2][0] == (5, 4)
        assert isinstance(context.parents[0].sent[0][2][1], str)
        with pytest.raises(FileNotFoundError):
            SharedMemory(name=context.parents[0].sent[0][2][1])
    finally:
        backend.close()
    assert context.parents[0].closed and context.children[0].closed
    assert context.processes[0].closed


@pytest.mark.parametrize(
    "response",
    (EOFError(), OSError(), ("result", 999, RESULT), ("result", 1, "bad-result")),
)
def test_crash_or_protocol_failure_disposes_generation_and_next_call_restarts(
    response: Any,
) -> None:
    context = Context([[READY, response], [READY, ("result", 2, RESULT)]])
    client = PaddleWorkerClient(context=context)
    with pytest.raises(RecognitionError):
        client.recognize(Image.new("RGB", (5, 4)))
    assert context.processes[0].closed
    assert context.parents[0].closed
    try:
        assert client.recognize(Image.new("RGB", (5, 4))) == RESULT
        assert len(context.processes) == 2
    finally:
        client.close()


@pytest.mark.parametrize("startup", (True, False))
def test_timeouts_terminate_and_allow_retry(startup: bool) -> None:
    context = Context([[] if startup else [READY], [READY]])
    client = PaddleWorkerClient(context=context, startup_timeout=0.005, recognition_timeout=0.005)
    with pytest.raises(RecognitionError, match="超时"):
        if startup:
            client.warmup()
        else:
            client.recognize(Image.new("RGB", (5, 4)))
    assert context.processes[0].terminated
    client.warmup()
    client.close()


@pytest.mark.parametrize("fail_start", (True, False))
def test_start_failure_or_startup_error_is_reported_and_cleaned(fail_start: bool) -> None:
    context = Context([[("error", 0, "初始化失败")]], fail_start=fail_start)
    client = PaddleWorkerClient(context=context)
    with pytest.raises(RecognitionError, match="初始化失败|无法启动"):
        client.warmup()
    assert context.parents[0].closed
    assert context.children[0].closed
    assert context.processes[0].closed


def test_close_is_idempotent_and_prevents_future_start() -> None:
    client = PaddleWorkerClient(context=Context([]))
    client.close()
    client.close()
    with pytest.raises(RecognitionError, match="已关闭"):
        client.warmup()


def test_close_interrupts_an_inflight_native_call_without_waiting_for_deadline() -> None:
    context = Context([[READY]])
    client = PaddleWorkerClient(context=context, recognition_timeout=60)
    client.warmup()
    waiting = Event()
    errors: list[Exception] = []
    connection = context.parents[0]
    original_poll = connection.poll

    def poll(timeout: float) -> bool:
        waiting.set()
        return original_poll(timeout)

    connection.poll = poll  # type: ignore[method-assign]

    def recognize() -> None:
        try:
            client.recognize(Image.new("RGB", (5, 4)))
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=recognize, daemon=True)
    thread.start()
    assert waiting.wait(2)
    client.close()
    thread.join(2)
    assert not thread.is_alive()
    assert errors and isinstance(errors[0], RecognitionError)


def _spawned_crashing_worker(connection: Any) -> None:
    """Exercise OS process death without loading native OCR in the test runner."""
    connection.send(READY)
    connection.recv()
    os._exit(23)


def test_real_spawn_child_abrupt_exit_does_not_kill_parent() -> None:
    class SpawnContext:
        def __init__(self) -> None:
            self.context = multiprocessing.get_context("spawn")

        def Pipe(self, **kwargs: Any) -> Any:  # noqa: N802
            return self.context.Pipe(**kwargs)

        def Process(self, **kwargs: Any) -> Any:  # noqa: N802
            kwargs["target"] = _spawned_crashing_worker
            return self.context.Process(**kwargs)

    client = PaddleWorkerClient(context=SpawnContext(), startup_timeout=15, recognition_timeout=5)
    parent_pid = os.getpid()
    try:
        with pytest.raises(RecognitionError, match="意外退出"):
            client.recognize(Image.new("RGB", (10, 10)))
        assert os.getpid() == parent_pid
        assert client._process is None
        # The next request reaches a newly spawned worker (and its deliberate crash).
        with pytest.raises(RecognitionError, match="意外退出"):
            client.recognize(Image.new("RGB", (10, 10)))
    finally:
        client.close()
