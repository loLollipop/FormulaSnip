"""A reusable spawn worker keeps MathCraft native failures outside the GUI.

The manager serializes calls. A duplex pipe has no queue feeder thread to join
after a child crash; every response carries the request ID. Only the child loads
MathCraft. A failed generation is discarded and the next call starts a fresh one.
"""

from __future__ import annotations

import logging
import multiprocessing
import sys
from contextlib import suppress
from multiprocessing.shared_memory import SharedMemory
from threading import Event, Lock, RLock
from time import monotonic
from typing import Any

from PIL import Image

from formulasnip.diagnostics import initialize_logging, log_exception
from formulasnip.domain import RecognitionResult
from formulasnip.exceptions import RecognitionError
from formulasnip.runtime import configure_runtime

_LOG = logging.getLogger(__name__)
STARTUP_TIMEOUT = 180.0
RECOGNITION_TIMEOUT = 120.0
MAX_RECOGNITION_IMAGE_PIXELS = 4_000_000


def _assign_kill_on_close_job(process: Any) -> int | None:
    """Best-effort Windows parent-death protection for the native worker."""

    if sys.platform != "win32" or process.pid is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        process_handle = kernel32.OpenProcess(
            0x0001 | 0x0100 | 0x1000, False, process.pid  # TERMINATE | SET_QUOTA | QUERY
        )
        if not process_handle:
            kernel32.CloseHandle(job)
            return None
        try:
            if not kernel32.AssignProcessToJobObject(job, process_handle):
                kernel32.CloseHandle(job)
                return None
        finally:
            kernel32.CloseHandle(process_handle)
        return int(job)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _close_windows_handle(handle: int | None) -> None:
    if sys.platform != "win32" or handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        pass


def _worker_main(connection: Any) -> None:
    configure_runtime()
    initialize_logging(worker=True)
    # Import here, after runtime setup, and never construct this backend in Qt.
    from formulasnip.recognition.mathcraft_backend import _InProcessMathCraftBackend

    try:
        backend = _InProcessMathCraftBackend()
        try:
            backend.warmup()
        except Exception as exc:
            log_exception("mathcraft-startup-failed", exc)
            connection.send(("error", 0, "MathCraft OCR 初始化失败，请检查模型下载后重试。"))
            return
        connection.send(("ready", 0, None))
        while True:
            command, request_id, payload = connection.recv()
            if command == "shutdown":
                return
            if command != "recognize":
                return
            try:
                size, memory_name = payload
                memory = SharedMemory(name=memory_name)
                try:
                    image = Image.frombytes("RGB", size, bytes(memory.buf))
                finally:
                    memory.close()
                _LOG.info("mathcraft-inference-start width=%d height=%d", *size)
                result = backend.recognize(image)
                _LOG.info("mathcraft-inference-done seconds=%.3f", result.elapsed_seconds)
                connection.send(("result", request_id, result))
            except Exception as exc:
                log_exception("mathcraft-recognition-failed", exc)
                connection.send((
                    "error", request_id, "MathCraft OCR 识别失败，请调整截图后重试。"
                ))
    except (EOFError, OSError):
        pass  # The GUI closed or was terminated.
    finally:
        connection.close()
        _LOG.info("mathcraft-worker-stop")


class MathCraftWorkerClient:
    def __init__(
        self,
        *,
        context: Any = None,
        startup_timeout: float = STARTUP_TIMEOUT,
        recognition_timeout: float = RECOGNITION_TIMEOUT,
    ) -> None:
        self._context = context or multiprocessing.get_context("spawn")
        self._startup_timeout = startup_timeout
        self._recognition_timeout = recognition_timeout
        self._process: Any = None
        self._connection: Any = None
        self._job_handle: int | None = None
        self._request_id = 0
        self._closed = False
        self._request_lock = Lock()
        self._state_lock = RLock()

    def warmup(self) -> None:
        with self._request_lock:
            self._ensure_started()

    def recognize(
        self,
        image: Image.Image,
        *,
        cancel_event: Event | None = None,
    ) -> RecognitionResult:
        width, height = image.size
        if (
            width <= 0
            or height <= 0
            or width * height > MAX_RECOGNITION_IMAGE_PIXELS
        ):
            raise RecognitionError(
                "截图尺寸过大（最多 400 万像素），请缩小截图范围后重试。"
            )
        self._raise_if_cancelled(cancel_event)
        with self._request_lock:
            self._raise_if_cancelled(cancel_event)
            self._ensure_started(cancel_event)
            self._raise_if_cancelled(cancel_event)
            self._request_id += 1
            request_id = self._request_id
            memory: SharedMemory | None = None
            try:
                # Keep pipe commands small: sending a full screenshot can block
                # indefinitely if native code hangs before the child reads it.
                rgb = image.convert("RGB")
                pixels = rgb.tobytes()
                memory = SharedMemory(create=True, size=len(pixels))
                memory.buf[:] = pixels
                self._connection.send(("recognize", request_id, (rgb.size, memory.name)))
                response = self._receive(
                    request_id,
                    self._recognition_timeout,
                    cancel_event,
                )
                if response[0] == "error":
                    raise RecognitionError(response[2])
                if response[0] != "result" or not isinstance(response[2], RecognitionResult):
                    raise RecognitionError("MathCraft OCR 返回异常，下一次识别将自动重启。")
                return response[2]
            except (OSError, EOFError, AttributeError, ValueError, MemoryError) as exc:
                self._dispose()
                raise self._crash_error() from exc
            except RecognitionError:
                self._dispose()
                raise
            finally:
                if memory is not None:
                    memory.close()
                    memory.unlink()

    def _ensure_started(self, cancel_event: Event | None = None) -> None:
        self._raise_if_cancelled(cancel_event)
        with self._state_lock:
            if self._closed:
                raise RecognitionError("公式识别服务已关闭。")
            if self._process is not None and self._process.is_alive():
                return
            self._dispose()
            parent = child = None
            try:
                parent, child = self._context.Pipe(duplex=True)
                process = self._context.Process(
                    target=_worker_main, args=(child,), name="FormulaSnip-MathCraft", daemon=True
                )
            except (OSError, MemoryError) as exc:
                for connection in (parent, child):
                    if connection is not None:
                        connection.close()
                log_exception("mathcraft-process-create-failed", exc)
                raise RecognitionError("无法创建 MathCraft OCR 进程，请释放内存后重试。") from exc
            self._connection, self._process = parent, process
            try:
                process.start()
                self._job_handle = _assign_kill_on_close_job(process)
                if sys.platform == "win32" and self._job_handle is None:
                    _LOG.warning("mathcraft-worker-job-protection-unavailable")
            except Exception as exc:
                log_exception("mathcraft-process-start-failed", exc)
                self._dispose()
                raise RecognitionError("无法启动 MathCraft OCR 识别进程，请稍后重试。") from exc
            finally:
                child.close()
            _LOG.info("mathcraft-worker-start pid=%s", process.pid)
        try:
            response = self._receive(0, self._startup_timeout, cancel_event)
            if response[0] == "error":
                raise RecognitionError(response[2])
            if response[0] != "ready":
                raise RecognitionError("MathCraft OCR 初始化响应异常，请重试。")
            _LOG.info("mathcraft-worker-ready")
        except (OSError, EOFError, AttributeError, ValueError) as exc:
            self._dispose()
            raise self._crash_error() from exc
        except RecognitionError:
            self._dispose()
            raise

    def _receive(
        self,
        request_id: int,
        timeout: float,
        cancel_event: Event | None = None,
    ) -> tuple[str, int, Any]:
        deadline = monotonic() + timeout
        connection, process = self._connection, self._process
        while True:
            self._raise_if_cancelled(cancel_event)
            remaining = deadline - monotonic()
            if remaining <= 0:
                _LOG.warning(
                    "mathcraft-worker-timeout stage=%s", "startup" if request_id == 0 else "infer"
                )
                raise RecognitionError("MathCraft OCR 响应超时，下一次识别将自动重启。")
            if connection.poll(min(remaining, 0.1)):
                response = connection.recv()
                if (
                    not isinstance(response, tuple)
                    or len(response) != 3
                    or response[1] != request_id
                ):
                    raise RecognitionError("MathCraft OCR 响应不匹配，下一次识别将自动重启。")
                return response
            if not process.is_alive():
                _LOG.error("mathcraft-worker-unexpected-exit code=%s", process.exitcode)
                raise self._crash_error()

    @staticmethod
    def _raise_if_cancelled(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RecognitionError("公式识别任务已取消。")

    @staticmethod
    def _crash_error() -> RecognitionError:
        return RecognitionError(
            "MathCraft OCR 识别进程意外退出（可能内存不足或模型运行异常）；"
            "软件仍可使用，下一次识别将自动重启。"
        )

    def _dispose(self, *, graceful: bool = False) -> None:
        with self._state_lock:
            process, connection, job_handle = (
                self._process,
                self._connection,
                self._job_handle,
            )
            self._process = self._connection = None
            self._job_handle = None
            try:
                if process is not None and process.pid is not None:
                    if graceful and process.is_alive() and connection is not None:
                        try:
                            connection.send(("shutdown", -1, None))
                            process.join(0.5)
                        except (OSError, EOFError, ValueError):
                            pass
                    if process.is_alive() and job_handle is not None:
                        _close_windows_handle(job_handle)
                        job_handle = None
                        process.join(1.0)
                    if process.is_alive():
                        try:
                            process.terminate()
                            process.join(1.0)
                        except (OSError, ValueError):
                            pass
                    if process.is_alive():
                        try:
                            process.kill()
                            process.join(1.0)
                        except (OSError, ValueError):
                            pass
                    _LOG.info("mathcraft-worker-exit code=%s", process.exitcode)
            finally:
                if connection is not None:
                    with suppress(OSError, ValueError):
                        connection.close()
                if process is not None:
                    with suppress(OSError, ValueError):
                        process.close()
                _close_windows_handle(job_handle)

    def close(self) -> None:
        # Do not wait for a hung model call/startup on the GUI's exit path.
        idle = self._request_lock.acquire(blocking=False)
        try:
            with self._state_lock:
                self._closed = True
                self._dispose(graceful=idle)
        finally:
            if idle:
                self._request_lock.release()

    def cancel_current(self) -> None:
        """Interrupt only the native generation currently owned by this client."""

        with self._state_lock:
            if self._closed or self._process is None:
                return
            self._dispose()
