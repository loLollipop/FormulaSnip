from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from formulasnip.ui.branding import application_icon
from formulasnip.update import (
    MAX_RELEASE_NOTES_LENGTH,
    ReleaseInfo,
    UpdateCancellation,
    UpdateCancelled,
    download_installer,
    fetch_latest_release,
)


def format_size(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


class UpdateDialog(QDialog):
    update_requested = Signal()
    remind_later_requested = Signal()

    def __init__(self, current_version: str, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release
        self.setObjectName("UpdateDialog")
        self.setWindowTitle("FormulaSnip 更新")
        self.setWindowIcon(application_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(False)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)
        title = QLabel("FormulaSnip 有新版本")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        versions = QLabel(f"当前 v{current_version}  ·  最新 v{release.version}")
        versions.setObjectName("PageSubtitle")
        layout.addWidget(versions)

        self.notes = QPlainTextEdit()
        self.notes.setObjectName("UpdateNotes")
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(180)
        notes = release.notes[:MAX_RELEASE_NOTES_LENGTH].strip()
        self.notes.setPlainText(notes or "本次更新未提供更新说明。")
        layout.addWidget(self.notes)

        size = QLabel(f"安装包 {format_size(release.asset.size)} · 下载后会校验 SHA-256")
        size.setObjectName("MutedText")
        layout.addWidget(size)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        self.status_label.setObjectName("FloatingStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.later_button = QPushButton("稍后提醒")
        self.update_button = QPushButton("立即更新")
        self.update_button.setObjectName("SettingsPrimary")
        self.later_button.clicked.connect(self._remind_later)
        self.update_button.clicked.connect(self.update_requested.emit)
        actions.addWidget(self.later_button)
        actions.addWidget(self.update_button)
        layout.addLayout(actions)

    @Slot()
    def _remind_later(self) -> None:
        self.hide()
        self.remind_later_requested.emit()

    def show_downloading(self) -> None:
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.status_label.setText("正在下载并校验安装包…")
        self.update_button.setEnabled(False)
        self.later_button.setEnabled(False)

    def set_download_progress(self, received: int, total: int) -> None:
        value = int(received * 100 / total) if total > 0 else 0
        self.progress_bar.setValue(min(max(value, 0), 100))

    def show_waiting_for_recognition(self) -> None:
        self.progress_bar.setValue(100)
        self.status_label.setText("安装包已就绪，当前识别结束后将自动更新…")

    def show_error(self, message: str) -> None:
        self.status_label.setText(message)
        self.update_button.setEnabled(True)
        self.later_button.setEnabled(True)

    def show_source_build_message(self) -> None:
        self.status_label.setText("源码或便携版不会改变安装方式，已打开 GitHub 发布页。")


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
            release = fetch_latest_release(
                self.current_version,
                cancel_event=self._cancellation,
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
    finished = Signal(object)
    failed = Signal(str)


class UpdateDownloadWorker(QRunnable):
    def __init__(self, release: ReleaseInfo, cache_directory: Path) -> None:
        super().__init__()
        self.release = release
        self.cache_directory = cache_directory
        self.signals = UpdateDownloadSignals()
        self._cancellation = UpdateCancellation()
        self.completed_path: Path | None = None

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
        try:
            path = download_installer(
                self.release.asset,
                self.cache_directory,
                progress=self._publish_progress,
                cancel_event=self._cancellation,
            )
        except UpdateCancelled:
            return
        except Exception as exc:
            message = str(exc).strip() or "下载更新失败。"
            self._publish(lambda: self.signals.failed.emit(message))
            return

        def publish_finished() -> None:
            self.completed_path = path
            self.signals.finished.emit(path)

        self._publish(publish_finished)
