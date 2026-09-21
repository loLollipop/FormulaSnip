from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

from formulasnip.core.limits import LATEX_LIMIT_MESSAGE, MAX_LATEX_CHARS
from formulasnip.core.preview import (
    build_mathjax_html,
    build_mathjax_update_script,
    mathjax_script_path,
)

_RENDER_TIMEOUT_MS = 15_000
_POLL_INTERVAL_MS = 75

try:
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInfo,
        QWebEngineUrlRequestInterceptor,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # A clear error surface remains available in broken installs.
    WEBENGINE_AVAILABLE = False
else:
    WEBENGINE_AVAILABLE = True


if WEBENGINE_AVAILABLE:

    class _LocalOnlyRequestInterceptor(QWebEngineUrlRequestInterceptor):
        """Block network access and unrelated local-file requests."""

        def __init__(self, allowed_script: str, parent: Any) -> None:
            super().__init__(parent)
            script_url = QUrl.fromLocalFile(allowed_script)
            self._allowed_file_urls = {
                script_url.toString(),
                QUrl.fromLocalFile(str(mathjax_script_path().parent.resolve()) + "/").toString(),
            }

        def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
            url = info.requestUrl()
            scheme = url.scheme().casefold()
            # QWebEngine implements setHtml() as an internal data: load.  Main-
            # frame navigation still rejects user-clicked data: links below.
            if scheme in {"about", "data"}:
                return
            if scheme == "file" and url.toString() in self._allowed_file_urls:
                return
            info.block(True)


    class _LocalOnlyPage(QWebEnginePage):
        def __init__(self, profile: QWebEngineProfile, parent: QWidget) -> None:
            super().__init__(profile, parent)
            self._allow_initial_document = False

        def set_preview_html(self, document: str, base_url: QUrl) -> None:
            """Permit exactly the internal data: navigation created by setHtml."""

            self._allow_initial_document = True
            self.setHtml(document, base_url)

        def acceptNavigationRequest(  # noqa: N802
            self,
            url: QUrl,
            navigation_type: QWebEnginePage.NavigationType,
            is_main_frame: bool,
        ) -> bool:
            allowed = (
                self._allow_initial_document
                and is_main_frame
                and navigation_type
                in {
                    QWebEnginePage.NavigationType.NavigationTypeOther,
                    # QWebEngine classifies setHtml() as a typed data: load.
                    QWebEnginePage.NavigationType.NavigationTypeTyped,
                }
                and url.scheme().casefold() == "data"
            )
            if allowed:
                self._allow_initial_document = False
            return allowed


class FormulaPreviewWidget(QWidget):
    """Offline MathJax preview; WebEngine failures never invoke another renderer."""

    rendered = Signal(int, str)
    failed = Signal(int, str)

    def __init__(self, *, webengine_enabled: bool | None = None) -> None:
        super().__init__()
        self._request_id = 0
        self._completed_request_id = 0
        self._current_backend = "unavailable"
        self._render_clock = QElapsedTimer()
        self._web_view: Any | None = None
        self._web_profile: Any | None = None
        self._web_page: Any | None = None
        self._request_interceptor: Any | None = None
        self._document_started = False
        self._document_loaded = False
        self._pending_formula: tuple[int, str] | None = None
        self._initialization_error = "Qt WebEngine 不可用，无法显示公式预览。"

        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._error_label = QLabel(self._initialization_error)
        self._error_label.setObjectName("FloatingMathJaxError")
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_label.setWordWrap(True)
        self._layout.addWidget(self._error_label)

        allow_webengine = WEBENGINE_AVAILABLE if webengine_enabled is None else webengine_enabled
        script = mathjax_script_path()
        if not script.is_file():
            self._initialization_error = "本地 MathJax 资源缺失，无法显示公式预览。"
        elif allow_webengine and WEBENGINE_AVAILABLE:
            try:
                self._initialize_webengine()
            except Exception as exc:
                self._initialization_error = f"Qt WebEngine 初始化失败：{exc}"
        self._error_label.setText(self._initialization_error)

        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_render_state)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_RENDER_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._render_timeout)

    @property
    def webengine_available(self) -> bool:
        return self._web_view is not None

    @property
    def web_view(self) -> Any | None:
        return self._web_view

    @property
    def error_text(self) -> str:
        return self._error_label.text()

    @property
    def current_backend(self) -> str:
        return self._current_backend

    @property
    def request_id(self) -> int:
        return self._request_id

    def set_formula(self, latex: str) -> int:
        if len(latex) > MAX_LATEX_CHARS:
            raise ValueError(LATEX_LIMIT_MESSAGE)
        self._request_id += 1
        request_id = self._request_id
        update_script = build_mathjax_update_script(latex, request_id)
        self._completed_request_id = 0
        self._render_clock.start()
        self._poll_timer.stop()
        self._timeout_timer.stop()

        if self._web_view is None:
            self._show_error(request_id, self._initialization_error)
            return request_id

        if not mathjax_script_path().is_file():
            self._show_error(request_id, "本地 MathJax 资源缺失，无法显示公式预览。")
            return request_id

        self._current_backend = "mathjax"
        self._layout.setCurrentWidget(self._web_view)
        self._pending_formula = (request_id, update_script)
        self._timeout_timer.start()
        self.warmup()
        self._dispatch_pending_formula()
        return request_id

    def warmup(self) -> None:
        """Load MathJax once without creating a user-visible preview request."""

        if self._web_page is None or self._document_started:
            return
        script = mathjax_script_path()
        if not script.is_file():
            return
        self._document_started = True
        self._document_loaded = False
        base_url = QUrl.fromLocalFile(str(script.parent.resolve()) + "/")
        try:
            self._web_page.set_preview_html(build_mathjax_html("x", 0), base_url)
        except Exception:
            self._document_started = False
            raise

    def _initialize_webengine(self) -> None:
        script = mathjax_script_path().resolve()
        self._web_profile = QWebEngineProfile(self)
        self._request_interceptor = _LocalOnlyRequestInterceptor(
            str(script), self._web_profile
        )
        self._web_profile.setUrlRequestInterceptor(self._request_interceptor)
        self._web_view = QWebEngineView(self)
        self._web_view.setObjectName("FloatingMathJaxPreview")
        self._web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._web_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._web_page = _LocalOnlyPage(self._web_profile, self._web_view)
        self._web_view.setPage(self._web_page)
        settings = self._web_view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
            False,
        )
        self._web_view.loadFinished.connect(self._web_load_finished)
        self._layout.addWidget(self._web_view)

    def _web_load_finished(self, successful: bool) -> None:
        self._document_loaded = bool(successful)
        if not successful:
            self._document_started = False
            if self._current_backend == "mathjax":
                self._show_error(self._request_id, "MathJax 页面加载失败。")
            return
        self._dispatch_pending_formula()

    def _dispatch_pending_formula(self) -> None:
        if (
            not self._document_loaded
            or self._web_page is None
            or self._pending_formula is None
        ):
            return
        request_id, update_script = self._pending_formula
        if request_id != self._request_id or self._current_backend != "mathjax":
            return
        self._pending_formula = None
        self._web_page.runJavaScript(
            update_script,
            lambda dispatched, expected=request_id: self._formula_dispatched(
                expected, dispatched
            ),
        )

    def _formula_dispatched(self, expected_request: int, dispatched: Any) -> None:
        if expected_request != self._request_id or self._current_backend != "mathjax":
            return
        if dispatched is not True:
            self._show_error(expected_request, "MathJax 预览页面尚未就绪。")
            return
        self._poll_render_state()

    def _poll_render_state(self) -> None:
        if self._web_page is None or self._current_backend != "mathjax":
            return
        expected_request = self._request_id
        self._web_page.runJavaScript(
            "JSON.stringify(window.__formulaPreview || null)",
            lambda state, expected=expected_request: self._handle_render_state(
                expected, state
            ),
        )

    def _handle_render_state(self, expected_request: int, state: Any) -> None:
        if expected_request != self._request_id or self._current_backend != "mathjax":
            return
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except (TypeError, ValueError):
                state = None
        if not isinstance(state, dict) or state.get("requestId") != expected_request:
            self._continue_polling_or_error(expected_request)
            return
        status = state.get("state")
        if status == "ready":
            self._timeout_timer.stop()
            if self._completed_request_id != expected_request:
                self._completed_request_id = expected_request
                self.rendered.emit(expected_request, "mathjax")
            return
        if status == "error":
            self._show_error(expected_request, str(state.get("error") or "MathJax 渲染失败"))
            return
        self._continue_polling_or_error(expected_request)

    def _continue_polling_or_error(self, expected_request: int) -> None:
        if expected_request != self._request_id:
            return
        if not self._render_clock.isValid() or self._render_clock.hasExpired(
            _RENDER_TIMEOUT_MS
        ):
            self._show_error(expected_request, "MathJax 渲染超时。")
            return
        self._poll_timer.start()

    def _render_timeout(self) -> None:
        if self._current_backend == "mathjax":
            self._show_error(self._request_id, "MathJax 渲染超时。")

    def _show_error(self, expected_request: int, detail: str) -> None:
        if expected_request != self._request_id:
            return
        self._timeout_timer.stop()
        self._pending_formula = None
        self._current_backend = "unavailable"
        self._error_label.setText(detail)
        self._layout.setCurrentWidget(self._error_label)
        QTimer.singleShot(
            0,
            lambda request=expected_request, message=detail: self._emit_failure(
                request, message
            ),
        )

    def _emit_failure(self, expected_request: int, detail: str) -> None:
        if expected_request == self._request_id:
            self.failed.emit(expected_request, detail)
