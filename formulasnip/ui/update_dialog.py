from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import TypeVar

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from formulasnip.ui.branding import application_icon
from formulasnip.update import (
    MAX_RELEASE_NOTES_LENGTH,
    ReleaseInfo,
    UpdateCancellation,
    UpdateCancelled,
    download_installer,
    fetch_latest_release,
    release_verified_installer,
)

_CANCELLATION_POLL_SECONDS = 0.02
_DOWNLOAD_OPERATION_SLOT = BoundedSemaphore(1)
_ResultT = TypeVar("_ResultT")
_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+(.+)$")
_ORDERED_PATTERN = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_LINK_PATTERN = re.compile(r"\[([^\]\n]+)]\([^\n)]+\)")


def _run_abandonable(
    operation: Callable[[], _ResultT],
    cancellation: UpdateCancellation,
    *,
    thread_name: str,
    operation_slot: BoundedSemaphore | None = None,
    abandon_result: Callable[[_ResultT], None] | None = None,
) -> _ResultT:
    """Run blocking network work without pinning its QThreadPool thread on cancel."""
    if cancellation.is_set():
        raise UpdateCancelled("Update operation cancelled.")
    if operation_slot is not None:
        while not operation_slot.acquire(timeout=_CANCELLATION_POLL_SECONDS):
            if cancellation.is_set():
                raise UpdateCancelled("Update operation cancelled.")
        if cancellation.is_set():
            operation_slot.release()
            raise UpdateCancelled("Update operation cancelled.")
    completed = Event()
    results: list[_ResultT] = []
    failures: list[Exception] = []
    state_lock = Lock()
    abandoned = False

    def discard(result: _ResultT) -> None:
        if abandon_result is not None:
            abandon_result(result)

    def invoke() -> None:
        try:
            result = operation()
            with state_lock:
                should_discard = abandoned or cancellation.is_set()
                if not should_discard:
                    results.append(result)
            if should_discard:
                discard(result)
        except Exception as exc:
            failures.append(exc)
        finally:
            if operation_slot is not None:
                operation_slot.release()
            completed.set()

    worker = Thread(target=invoke, name=thread_name, daemon=True)
    try:
        worker.start()
    except Exception:
        if operation_slot is not None:
            operation_slot.release()
        raise
    while not completed.wait(_CANCELLATION_POLL_SECONDS):
        if cancellation.is_set():
            with state_lock:
                abandoned = True
                discarded = tuple(results)
                results.clear()
            for result in discarded:
                discard(result)
            raise UpdateCancelled("Update operation cancelled.")
    if cancellation.is_set():
        with state_lock:
            abandoned = True
            discarded = tuple(results)
            results.clear()
        for result in discarded:
            discard(result)
        raise UpdateCancelled("Update operation cancelled.")
    if failures:
        raise failures[0]
    if not results:
        raise RuntimeError("The background update operation returned no result.")
    return results[0]


def format_size(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def _format_inline_note(text: str) -> str:
    """Render a safe, deliberately small subset of Markdown inline syntax."""
    without_links = _LINK_PATTERN.sub(r"\1", text.strip())
    escaped = html.escape(without_links, quote=False)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"__([^_\n]+)__", r"<strong>\1</strong>", escaped)


def format_release_notes(notes: str) -> str:
    """Convert untrusted GitHub release notes into restrained, readable HTML."""
    normalized = notes[:MAX_RELEASE_NOTES_LENGTH].replace("\r\n", "\n").replace(
        "\r", "\n"
    )
    if not normalized.strip():
        normalized = "本次更新未提供更新说明。"

    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{'<br>'.join(paragraph)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue

        heading_match = _HEADING_PATTERN.match(raw_line)
        bullet_match = _BULLET_PATTERN.match(raw_line)
        ordered_match = _ORDERED_PATTERN.match(raw_line)
        if heading_match:
            flush_paragraph()
            close_list()
            blocks.append(
                f'<p class="release-heading">'
                f"{_format_inline_note(heading_match.group(1))}</p>"
            )
            continue

        item_match = bullet_match or ordered_match
        if item_match:
            flush_paragraph()
            required_kind = "ul" if bullet_match else "ol"
            if list_kind != required_kind:
                close_list()
                blocks.append(f"<{required_kind}>")
                list_kind = required_kind
            blocks.append(f"<li>{_format_inline_note(item_match.group(1))}</li>")
            continue

        close_list()
        paragraph.append(_format_inline_note(line))

    flush_paragraph()
    close_list()
    body = "".join(blocks)
    return f"""
<!doctype html>
<html>
<head>
<style>
body {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    line-height: 1.55;
    margin: 5px 8px;
}}
p {{ margin: 0 0 9px 0; }}
p.release-heading {{ font-size: 14px; font-weight: 600; margin: 10px 0 6px 0; }}
ul, ol {{ margin: 2px 0 10px 20px; padding: 0; }}
li {{ margin: 0 0 5px 0; }}
code {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 12px; }}
</style>
</head>
<body>{body}</body>
</html>
""".strip()


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class UpdateDialog(QDialog):
    update_requested = Signal()
    remind_later_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, current_version: str, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release
        self._busy_state = "idle"
        self._cancel_emitted = False
        self._remind_emitted = False
        self.setObjectName("UpdateDialog")
        self.setWindowTitle("FormulaSnip 更新")
        self.setWindowIcon(application_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(False)
        self.setMinimumWidth(600)
        self.resize(620, 570)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("UpdateHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 22)
        header_layout.setSpacing(14)

        app_icon = QLabel()
        app_icon.setObjectName("UpdateAppIcon")
        app_icon.setFixedSize(48, 48)
        app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_icon.setPixmap(application_icon().pixmap(QSize(30, 30)))
        app_icon.setAccessibleName("FormulaSnip 应用图标")
        header_layout.addWidget(app_icon)

        heading_layout = QVBoxLayout()
        heading_layout.setContentsMargins(0, 1, 0, 1)
        heading_layout.setSpacing(4)
        title = QLabel("发现新版本")
        title.setObjectName("UpdateTitle")
        subtitle = QLabel("FormulaSnip 已准备好升级")
        subtitle.setObjectName("UpdateSubtitle")
        heading_layout.addWidget(title)
        heading_layout.addWidget(subtitle)
        header_layout.addLayout(heading_layout, 1)
        layout.addWidget(header)

        self.content_scroll = QScrollArea()
        self.content_scroll.setObjectName("UpdateContentScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content_scroll.setMinimumHeight(0)

        content = QWidget()
        content.setObjectName("UpdateContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 22, 28, 22)
        content_layout.setSpacing(13)

        version_card = QFrame()
        version_card.setObjectName("UpdateVersionCard")
        version_layout = QHBoxLayout(version_card)
        version_layout.setContentsMargins(18, 13, 18, 13)
        version_layout.setSpacing(18)

        current_layout = QVBoxLayout()
        current_layout.setSpacing(3)
        current_caption = QLabel("当前版本")
        current_caption.setObjectName("UpdateVersionCaption")
        self.current_version_label = QLabel(f"v{current_version}")
        self.current_version_label.setObjectName("UpdateCurrentVersion")
        current_layout.addWidget(current_caption)
        current_layout.addWidget(self.current_version_label)
        version_layout.addLayout(current_layout, 1)

        version_arrow = QLabel("→")
        version_arrow.setObjectName("UpdateVersionArrow")
        version_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_arrow.setAccessibleName("升级到")
        version_layout.addWidget(version_arrow)

        latest_layout = QVBoxLayout()
        latest_layout.setSpacing(3)
        latest_caption = QLabel("最新版本")
        latest_caption.setObjectName("UpdateVersionCaption")
        self.latest_version_label = QLabel(f"v{release.version}")
        self.latest_version_label.setObjectName("UpdateLatestVersion")
        latest_layout.addWidget(latest_caption)
        latest_layout.addWidget(self.latest_version_label)
        version_layout.addLayout(latest_layout, 1)
        content_layout.addWidget(version_card)

        notes_title = QLabel("更新内容")
        notes_title.setObjectName("UpdateSectionTitle")
        content_layout.addWidget(notes_title)

        self.notes = QTextBrowser()
        self.notes.setObjectName("UpdateNotes")
        self.notes.setReadOnly(True)
        self.notes.setOpenExternalLinks(False)
        self.notes.setOpenLinks(False)
        self.notes.setAccessibleName("更新内容")
        self.notes.setAccessibleDescription("FormulaSnip 新版本的发布说明")
        self.notes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes.setMinimumHeight(132)
        self.notes.setMaximumHeight(220)
        self.notes.setHtml(format_release_notes(release.notes))
        notes_title.setBuddy(self.notes)
        content_layout.addWidget(self.notes, 1)

        metadata = QHBoxLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(8)
        size_label = QLabel(f"安装包  {format_size(release.asset.size)}")
        size_label.setObjectName("UpdateMetaChip")
        checksum_label = QLabel("完整性校验  SHA-256")
        checksum_label.setObjectName("UpdateMetaChip")
        metadata.addWidget(size_label)
        metadata.addWidget(checksum_label)
        metadata.addStretch(1)
        content_layout.addLayout(metadata)

        self.status_panel = QFrame()
        self.status_panel.setObjectName("UpdateStatusPanel")
        self.status_panel.setProperty("state", "info")
        status_layout = QVBoxLayout(self.status_panel)
        status_layout.setContentsMargins(13, 10, 13, 10)
        status_layout.setSpacing(7)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        self.status_label = QLabel("")
        self.status_label.setObjectName("UpdateStatusLabel")
        self.status_label.setWordWrap(True)
        self.progress_detail_label = QLabel("")
        self.progress_detail_label.setObjectName("UpdateProgressDetail")
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress_detail_label)
        status_layout.addLayout(status_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("UpdateProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        status_layout.addWidget(self.progress_bar)
        self.status_panel.hide()
        content_layout.addWidget(self.status_panel)
        self.content_scroll.setWidget(content)
        layout.addWidget(self.content_scroll, 1)

        footer = QFrame()
        footer.setObjectName("UpdateFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(28, 17, 28, 18)
        actions.setSpacing(10)
        actions.addStretch(1)
        self.later_button = QPushButton("稍后提醒")
        self.later_button.setObjectName("UpdateLaterButton")
        self.update_button = QPushButton("立即更新")
        self.update_button.setObjectName("SettingsPrimary")
        self.later_button.setMinimumWidth(102)
        self.update_button.setMinimumWidth(116)
        self.later_button.clicked.connect(self._remind_later)
        self.update_button.clicked.connect(self.update_requested.emit)
        actions.addWidget(self.later_button)
        actions.addWidget(self.update_button)
        layout.addWidget(footer)

    @Slot()
    def _remind_later(self) -> None:
        if self._busy_state in {"downloading", "waiting", "cancelling"}:
            self._request_cancel()
            return
        self.hide()
        self._emit_remind_later()

    def _emit_remind_later(self) -> None:
        if self._remind_emitted:
            return
        self._remind_emitted = True
        self.remind_later_requested.emit()

    def _request_cancel(self) -> None:
        if self._cancel_emitted:
            return
        self._cancel_emitted = True
        self._busy_state = "cancelling"
        self.later_button.setText("正在取消…")
        self.later_button.setEnabled(False)
        self._show_status("info", "正在取消更新…", progress=False)
        self.cancel_requested.emit()

    def show_downloading(self) -> None:
        self._busy_state = "downloading"
        self._cancel_emitted = False
        self.progress_bar.setValue(0)
        self._show_status("progress", "正在下载更新", progress=True, detail="0%")
        self.update_button.setText("正在更新…")
        self.update_button.setEnabled(False)
        self.later_button.setText("取消下载")
        self.later_button.setEnabled(True)

    def set_download_progress(self, received: int, total: int) -> None:
        value = int(received * 100 / total) if total > 0 else 0
        value = min(max(value, 0), 100)
        self.progress_bar.setValue(value)
        self.progress_detail_label.setText(f"{value}%")
        self.status_label.setText(
            "正在校验安装包" if value >= 100 else "正在下载更新"
        )

    def show_waiting_for_recognition(self) -> None:
        self._busy_state = "waiting"
        self._cancel_emitted = False
        self.progress_bar.setValue(100)
        self._show_status(
            "waiting",
            "安装包已就绪，当前识别完成后将自动安装",
            progress=False,
        )
        self.update_button.setText("等待安装")
        self.update_button.setEnabled(False)
        self.later_button.setText("取消安装")
        self.later_button.setEnabled(True)

    def show_error(self, message: str) -> None:
        self._busy_state = "idle"
        self._show_status("error", message, progress=False)
        self.update_button.setText("重试更新")
        self.update_button.setEnabled(True)
        self.later_button.setText("关闭")
        self.later_button.setEnabled(True)

    def show_cancelled(self) -> None:
        self._busy_state = "idle"
        self._show_status("info", "更新已取消", progress=False)
        self.update_button.setText("重新下载")
        self.update_button.setEnabled(True)
        self.later_button.setText("关闭")
        self.later_button.setEnabled(True)

    def show_source_build_message(self) -> None:
        self._busy_state = "idle"
        self._show_status(
            "info",
            "当前为源码或便携版本，已为你打开 GitHub 发布页",
            progress=False,
        )
        self.update_button.setText("再次打开发布页")

    def reject(self) -> None:
        if self._busy_state in {"downloading", "waiting", "cancelling"}:
            self._request_cancel()
            self.hide()
            return
        self._emit_remind_later()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._busy_state in {"downloading", "waiting", "cancelling"}:
            self._request_cancel()
        else:
            self._emit_remind_later()
        event.accept()

    def _show_status(
        self,
        state: str,
        message: str,
        *,
        progress: bool,
        detail: str = "",
    ) -> None:
        self.status_panel.setProperty("state", state)
        self.status_label.setText(message)
        self.progress_detail_label.setText(detail)
        self.progress_detail_label.setVisible(bool(detail))
        self.progress_bar.setVisible(progress)
        self.status_panel.show()
        _repolish(self.status_panel)
        QTimer.singleShot(
            0,
            lambda: self.content_scroll.ensureWidgetVisible(self.status_panel, 0, 14),
        )


class UpdateCheckSignals(QObject):
    available = Signal(object)
    no_update = Signal()
    failed = Signal(str)


class UpdateCheckWorker(QRunnable):
    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = current_version
        self.signals = UpdateCheckSignals()
        self._cancellation = UpdateCancellation()

    def cancel(self) -> None:
        self._cancellation.cancel()

    def _publish(self, callback: Callable[[], None]) -> bool:
        try:
            return self._cancellation.run_if_active(callback)
        except RuntimeError:
            return False

    @Slot()
    def run(self) -> None:
        try:
            release = _run_abandonable(
                lambda: fetch_latest_release(
                    self.current_version,
                    cancel_event=self._cancellation,
                ),
                self._cancellation,
                thread_name="FormulaSnip-UpdateCheck",
            )
        except UpdateCancelled:
            return
        except Exception as exc:
            message = str(exc).strip() or "检查更新失败。"
            self._publish(lambda: self.signals.failed.emit(message))
            return
        if release is None:
            self._publish(self.signals.no_update.emit)
        else:
            self._publish(lambda: self.signals.available.emit(release))


class UpdateDownloadSignals(QObject):
    progress = Signal(object, object)
    finished = Signal(object, object)
    failed = Signal(str)


class UpdateDownloadWorker(QRunnable):
    def __init__(self, release: ReleaseInfo, cache_directory: Path) -> None:
        super().__init__()
        self.release = release
        self.cache_directory = cache_directory
        self.signals = UpdateDownloadSignals()
        self._cancellation = UpdateCancellation()
        self.completed_path: Path | None = None
        self.completed_release: ReleaseInfo | None = None

    def cancel(self) -> None:
        self._cancellation.cancel()

    def _publish(self, callback: Callable[[], None]) -> bool:
        try:
            return self._cancellation.run_if_active(callback)
        except RuntimeError:
            return False

    def _publish_progress(self, received: int, total: int) -> None:
        self._publish(lambda: self.signals.progress.emit(received, total))

    @Slot()
    def run(self) -> None:
        completed_release = self.release
        try:
            path = _run_abandonable(
                lambda: download_installer(
                    self.release.asset,
                    self.cache_directory,
                    progress=self._publish_progress,
                    cancel_event=self._cancellation,
                ),
                self._cancellation,
                thread_name="FormulaSnip-UpdateDownload",
                operation_slot=_DOWNLOAD_OPERATION_SLOT,
                abandon_result=release_verified_installer,
            )
        except UpdateCancelled:
            return
        except Exception as exc:
            fallback_asset = self.release.fallback_asset
            if fallback_asset is None:
                message = str(exc).strip() or "下载更新失败。"
                self._publish(lambda: self.signals.failed.emit(message))
                return
            completed_release = replace(
                self.release,
                asset=fallback_asset,
                fallback_asset=None,
            )
            try:
                path = _run_abandonable(
                    lambda: download_installer(
                        completed_release.asset,
                        self.cache_directory,
                        progress=self._publish_progress,
                        cancel_event=self._cancellation,
                    ),
                    self._cancellation,
                    thread_name="FormulaSnip-UpdateDownload-Fallback",
                    operation_slot=_DOWNLOAD_OPERATION_SLOT,
                    abandon_result=release_verified_installer,
                )
            except UpdateCancelled:
                return
            except Exception as fallback_exc:
                message = str(fallback_exc).strip() or "下载更新失败。"
                self._publish(lambda: self.signals.failed.emit(message))
                return

        def publish_finished() -> None:
            self.completed_path = path
            self.completed_release = completed_release
            self.signals.finished.emit(path, completed_release)

        if not self._publish(publish_finished):
            release_verified_installer(path)
