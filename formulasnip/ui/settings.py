from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSettings,
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from formulasnip.credentials import CredentialError, OpenAIApiKeyStore
from formulasnip.recognition import backend_summaries
from formulasnip.recognition.openai_correction import (
    AICorrectionError,
    validate_ai_base_url,
    validate_ai_model_id,
)
from formulasnip.ui.branding import (
    TUTORIAL_FORMULA_LATEX,
    application_icon,
    application_version,
    themed_brand_pixmap,
    tutorial_formula_image,
)
from formulasnip.ui.styles import (
    ACCENT_THEME_SWATCHES,
    DEFAULT_ACCENT_THEME,
    apply_application_theme,
    current_accent_color,
    normalize_accent_theme,
    theme_accent_color,
)
from formulasnip.ui.worker import CompatibleModelWorker

RECOGNITION_MODES = ("mathcraft",)
ORB_COLORS = ("blue", "green", "orange")
RESULT_THEMES = ("dark", "light")
LEGACY_DEFAULT_RING_COLOR = "#5D83F3"
DEFAULT_RING_COLOR = "#7C6CF7"
RING_PRESETS = {
    "blue": DEFAULT_RING_COLOR,
    "green": "#22C7A9",
    "orange": "#FF8A4C",
    "rose": "#F45D92",
    "cyan": "#27B8D1",
}
RING_PRESET_LABELS = {
    "blue": "电光紫",
    "green": "青绿",
    "orange": "橙色",
    "rose": "玫红",
    "cyan": "冰蓝",
}
THEME_ACCENT_LABELS = {
    "blue": "星际蓝",
    "violet": "电光紫",
    "cyan": "极光青",
    "teal": "薄荷绿",
}
MAX_LOGO_BYTES = 12 * 1024 * 1024
MAX_LOGO_SIDE = 4096
MAX_LOGO_PIXELS = 16_000_000
LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SETTINGS_ERROR_MESSAGE = "无法保存设置，请检查可用空间和访问权限后重试。"
_SETTINGS_IO_LOCK = RLock()


class PreferencesSaveError(RuntimeError):
    """Settings did not reach persistent storage; never report a saved state."""

    def __init__(self, message: str, *, format_error: bool = False) -> None:
        super().__init__(message)
        self.format_error = format_error


@contextmanager
def _isolated_ini_reader(content: bytes) -> Iterator[QSettings]:
    """Parse INI bytes with Qt without touching the live QSettings cache."""

    temporary_path: Path | None = None
    reader: QSettings | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="formulasnip-settings-read-",
            suffix=".ini",
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        temporary_path.write_bytes(content)
        reader = QSettings(str(temporary_path), QSettings.Format.IniFormat)
        reader.allKeys()
        if reader.status() != QSettings.Status.NoError:
            raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE, format_error=True)
        yield reader
    except PreferencesSaveError:
        raise
    except OSError as exc:
        raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE) from exc
    finally:
        if reader is not None:
            del reader
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink()


def _quiesce_ini_cache(
    path: Path,
    original: bytes,
    *,
    originally_existed: bool,
    canonical_values: Mapping[str, object],
) -> None:
    """Drain Qt's shared pending cache while the exact file is protected."""

    backup_path: Path | None = None
    original_moved = False
    working_created = False
    cache_dirtied = False
    cache_drained = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, backup_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".protected",
            dir=path.parent,
        )
        os.close(descriptor)
        backup_path = Path(backup_name)
        current_exists = path.exists()
        current = path.read_bytes() if current_exists else b""
        if current_exists != originally_existed or current != original:
            raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
        if originally_existed:
            os.replace(path, backup_path)
            original_moved = True
        path.write_bytes(b"")
        working_created = True
        cache_dirtied = True
        for _attempt in range(2):
            cache = QSettings(str(path), QSettings.Format.IniFormat)
            cache.clear()
            for key, value in canonical_values.items():
                cache.setValue(key, value)
            cache.sync()
            cache_drained = cache.status() == QSettings.Status.NoError
            del cache
            if cache_drained:
                break
        if not cache_drained:
            raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
        path.unlink(missing_ok=True)
        working_created = False
        if originally_existed:
            assert backup_path is not None
            os.replace(backup_path, path)
            backup_path = None
            original_moved = False
    except PreferencesSaveError:
        raise
    except OSError as exc:
        raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE) from exc
    finally:
        if working_created and (not cache_dirtied or cache_drained):
            with suppress(OSError):
                path.unlink()
        if original_moved and (not cache_dirtied or cache_drained):
            assert backup_path is not None
            with suppress(OSError):
                os.replace(backup_path, path)
        elif not original_moved and backup_path is not None:
            # Only an unused mkstemp placeholder can exist in this branch.
            with suppress(OSError):
                backup_path.unlink()


def _protect_ini_from_pending_cache(settings: QSettings) -> None:
    """Preserve disk bytes across Qt's delayed auto-sync of pending values."""

    if type(settings) is not QSettings or settings.format() != QSettings.Format.IniFormat:
        return
    path = Path(settings.fileName())
    original: bytes | None = None
    try:
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
        original = path.read_bytes()
        canonical_values: dict[str, object] = {
            "recognition/ai_correction_enabled": False
        }
        with suppress(PreferencesSaveError), _isolated_ini_reader(original) as reader:
            canonical_values = {
                key: reader.value(key) for key in reader.allKeys()
            }
            canonical_values.setdefault(
                "recognition/ai_correction_enabled",
                False,
            )
        _quiesce_ini_cache(
            path,
            original,
            originally_existed=True,
            canonical_values=canonical_values,
        )
    except (OSError, PreferencesSaveError):
        if original is not None:
            for suffix in (".recovery", ".recovery.1", ".recovery.2"):
                recovery_path = path.with_name(f"{path.name}{suffix}")
                try:
                    with recovery_path.open("xb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    break
                except FileExistsError:
                    continue
                except OSError:
                    break
        # If the filesystem cannot host the protected drain, replace any queued
        # opt-in in Qt's shared cache with the privacy-safe state. A later Qt
        # auto-sync may normalize the file, but it cannot silently enable upload.
        settings.setValue("recognition/ai_correction_enabled", False)


def _validated_ini_bytes(settings: QSettings) -> tuple[Path, bytes, bool]:
    """Read an INI file and validate it with an isolated real Qt parser."""

    path = Path(settings.fileName())
    try:
        existed = path.exists()
        if not existed:
            return path, b"", False
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE, format_error=True)
        content = path.read_bytes()
        content.decode("utf-8-sig")
    except PreferencesSaveError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE, format_error=True) from exc
    with _isolated_ini_reader(content):
        pass
    return path, content, True


def _settings_source_has_format_error(settings: QSettings) -> bool:
    if settings.status() == QSettings.Status.FormatError:
        with _SETTINGS_IO_LOCK:
            _protect_ini_from_pending_cache(settings)
        return True
    if type(settings) is QSettings and settings.format() == QSettings.Format.IniFormat:
        try:
            _validated_ini_bytes(settings)
        except PreferencesSaveError as exc:
            if exc.format_error:
                with _SETTINGS_IO_LOCK:
                    _protect_ini_from_pending_cache(settings)
            return exc.format_error
    return False


def write_settings_values(
    settings: QSettings,
    values: Mapping[str, object],
    *,
    remove: Iterable[str] = (),
) -> QSettings:
    """Persist settings, using an isolated atomic transaction for real INI stores."""

    if type(settings) is QSettings and settings.format() == QSettings.Format.IniFormat:
        with _SETTINGS_IO_LOCK:
            if settings.status() != QSettings.Status.NoError:
                _protect_ini_from_pending_cache(settings)
                raise PreferencesSaveError(
                    SETTINGS_ERROR_MESSAGE,
                    format_error=settings.status() == QSettings.Status.FormatError,
                )
            try:
                path, original, originally_existed = _validated_ini_bytes(settings)
            except PreferencesSaveError:
                _protect_ini_from_pending_cache(settings)
                raise
            temporary_path: Path | None = None
            temporary_settings: QSettings | None = None
            original_values: dict[str, object] = {}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    dir=path.parent,
                )
                os.close(descriptor)
                temporary_path = Path(temporary_name)
                temporary_path.write_bytes(original)
                temporary_settings = QSettings(
                    str(temporary_path), QSettings.Format.IniFormat
                )
                temporary_settings.allKeys()
                if temporary_settings.status() != QSettings.Status.NoError:
                    raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE, format_error=True)
                original_values = {
                    key: temporary_settings.value(key)
                    for key in temporary_settings.allKeys()
                }
                for key in remove:
                    temporary_settings.remove(key)
                for key, value in values.items():
                    temporary_settings.setValue(key, value)
                temporary_settings.sync()
                if temporary_settings.status() != QSettings.Status.NoError:
                    raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
                temporary_settings.allKeys()
                del temporary_settings
                temporary_settings = None
                _validated_ini_bytes(
                    QSettings(str(temporary_path), QSettings.Format.IniFormat)
                )
                current_exists = path.exists()
                current = path.read_bytes() if current_exists else b""
                if current_exists != originally_existed or current != original:
                    raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
                _quiesce_ini_cache(
                    path,
                    original,
                    originally_existed=originally_existed,
                    canonical_values=original_values,
                )
                current_exists = path.exists()
                current = path.read_bytes() if current_exists else b""
                if current_exists != originally_existed or current != original:
                    raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE)
                os.replace(temporary_path, path)
                temporary_path = None
            except PreferencesSaveError:
                _protect_ini_from_pending_cache(settings)
                raise
            except OSError as exc:
                _protect_ini_from_pending_cache(settings)
                raise PreferencesSaveError(SETTINGS_ERROR_MESSAGE) from exc
            finally:
                if temporary_settings is not None:
                    del temporary_settings
                if temporary_path is not None:
                    with suppress(OSError):
                        temporary_path.unlink()
            # Cache reconciliation finished before the only commit. Nothing that
            # can fail or queue another write runs after the atomic replacement.
            return QSettings(str(path), QSettings.Format.IniFormat)

    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise PreferencesSaveError(
            SETTINGS_ERROR_MESSAGE,
            format_error=settings.status() == QSettings.Status.FormatError,
        )
    for key in remove:
        settings.remove(key)
    for key, value in values.items():
        settings.setValue(key, value)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise PreferencesSaveError(
            SETTINGS_ERROR_MESSAGE,
            format_error=settings.status() == QSettings.Status.FormatError,
        )
    return settings


def read_settings_value(
    settings: QSettings,
    key: str,
    default: object = None,
) -> object:
    """Read one value without flushing a live INI object's pending cache."""

    if type(settings) is QSettings and settings.format() == QSettings.Format.IniFormat:
        with _SETTINGS_IO_LOCK:
            if settings.status() != QSettings.Status.NoError:
                _protect_ini_from_pending_cache(settings)
                return default
            try:
                _path, content, _existed = _validated_ini_bytes(settings)
                with _isolated_ini_reader(content) as reader:
                    return reader.value(key, default)
            except PreferencesSaveError as exc:
                if exc.format_error:
                    _protect_ini_from_pending_cache(settings)
                return default
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        return default
    return settings.value(key, default)


GITHUB_MARK_PATH = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59"
    ".4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94"
    "-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 "
    "1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64"
    "-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 "
    ".67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 "
    "2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 "
    "3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 "
    "2.2 0 .21.15.46.55.38A7.995 7.995 0 0016 8c0-4.42-3.58-8-8-8z"
)
LINE_ICON_PATHS = {
    "general": (
        '<path d="M4 6h10m4 0h2M4 12h2m4 0h10M4 18h7m4 0h5"/>'
        '<circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/>'
        '<circle cx="13" cy="18" r="2"/>'
    ),
    "recognition": (
        '<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M8 '
        '21H5a2 2 0 0 1-2-2v-3m13 5h3a2 2 0 0 0 2-2v-3"/>'
        '<path d="M7 15l2-6 3 6 2-4 3 4"/>'
    ),
    "orb": (
        '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.5"/>'
        '<path d="M12 2v2m0 16v2M2 12h2m16 0h2"/>'
    ),
    "tutorial": (
        '<path d="M4 5h5a3 3 0 0 1 3 3v12a4 4 0 0 0-4-4H4z"/>'
        '<path d="M20 5h-5a3 3 0 0 0-3 3v12a4 4 0 0 1 4-4h4z"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 '
        '12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>'
    ),
    "moon": '<path d="M20 15.5A8 8 0 0 1 8.5 4 8 8 0 1 0 20 15.5z"/>',
}


def normalize_hex_color(value: object, default: str = DEFAULT_RING_COLOR) -> str:
    """Return a canonical #RRGGBB color or the supplied safe default."""
    if isinstance(value, str):
        candidate = value.strip()
        color = QColor(candidate)
        if len(candidate) == 7 and candidate.startswith("#") and color.isValid():
            return color.name(QColor.NameFormat.HexRgb).upper()
    return default


def github_mark_icon(color: str) -> QIcon:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f'<path fill="{color}" d="{GITHUB_MARK_PATH}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, 32, 32))
    painter.end()
    return QIcon(pixmap)


def line_icon(name: str, color: str) -> QIcon:
    body = LINE_ICON_PATHS.get(name, "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(2, 2, 28, 28))
    painter.end()
    return QIcon(pixmap)


def read_logo_image(path: object, target_size: int = 40) -> QImage | None:
    """Safely decode a small logo preview without expanding oversized input."""
    if not isinstance(path, str) or not path.strip():
        return None
    candidate = Path(path).expanduser()
    try:
        if (
            not candidate.is_file()
            or candidate.suffix.lower() not in LOGO_SUFFIXES
            or candidate.stat().st_size > MAX_LOGO_BYTES
        ):
            return None
    except OSError:
        return None

    reader = QImageReader(str(candidate))
    reader.setAutoTransform(True)
    reader.setDecideFormatFromContent(True)
    expected_format = candidate.suffix.lower().lstrip(".")
    if expected_format == "jpg":
        expected_format = "jpeg"
    actual_format = bytes(reader.format()).decode("ascii", errors="replace").lower()
    if actual_format not in {"png", "jpeg", "webp", "bmp"}:
        return None
    if actual_format != expected_format:
        return None
    size = reader.size()
    if not size.isValid():
        return None
    if (
        size.width() > MAX_LOGO_SIDE
        or size.height() > MAX_LOGO_SIDE
        or size.width() * size.height() > MAX_LOGO_PIXELS
    ):
        return None
    scaled = size.scaled(target_size, target_size, Qt.AspectRatioMode.KeepAspectRatio)
    reader.setScaledSize(scaled)
    image = reader.read()
    return None if image.isNull() else image


@dataclass(frozen=True, slots=True)
class FloatingPreferences:
    # The first four fields intentionally retain the V3 positional API.
    recognition_mode: str = "mathcraft"
    orb_color: str = "blue"
    result_theme: str = "dark"
    show_settings_on_startup: bool = True
    ring_color: str | None = None
    logo_path: str = ""
    ai_correction_enabled: bool = False
    ai_base_url: str = ""
    ai_model: str = ""
    auto_check_updates: bool = True
    accent_theme: str = DEFAULT_ACCENT_THEME

    @property
    def effective_ring_color(self) -> str:
        if self.ring_color is not None:
            return normalize_hex_color(self.ring_color)
        return RING_PRESETS.get(self.orb_color, DEFAULT_RING_COLOR)

    @property
    def effective_logo_path(self) -> str:
        if read_logo_image(self.logo_path) is None:
            return ""
        try:
            return str(Path(self.logo_path).expanduser().resolve())
        except OSError:
            return ""

    @property
    def effective_accent_theme(self) -> str:
        return normalize_accent_theme(self.accent_theme)

    @classmethod
    def load(cls, settings: QSettings) -> FloatingPreferences:
        if _settings_source_has_format_error(settings):
            # Do not delete or rewrite a damaged INI/native store at startup.
            return cls()
        if type(settings) is QSettings and settings.format() == QSettings.Format.IniFormat:
            with _SETTINGS_IO_LOCK:
                if settings.status() == QSettings.Status.AccessError:
                    _protect_ini_from_pending_cache(settings)
                    return cls()
                path = Path(settings.fileName())
                if not path.exists():
                    # Preserve the conventional QSettings API for a newly created
                    # store while there is no existing file that could be damaged.
                    settings.sync()
                    if settings.status() != QSettings.Status.NoError:
                        return cls()
                try:
                    _path, content, _existed = _validated_ini_bytes(settings)
                    with _isolated_ini_reader(content) as reader:
                        stored_values = {
                            key: reader.value(key) for key in reader.allKeys()
                        }
                except PreferencesSaveError:
                    return cls()

            def stored_value(key: str, default: object = None) -> object:
                return stored_values.get(key, default)

        else:
            settings.sync()
            settings.allKeys()
            if settings.status() != QSettings.Status.NoError:
                return cls()

            def stored_value(key: str, default: object = None) -> object:
                return settings.value(key, default)

        legacy_orb = _choice(stored_value("appearance/orb_color"), ORB_COLORS, "blue")
        legacy_theme = _choice(
            stored_value("appearance/result_theme"), RESULT_THEMES, "dark"
        )
        theme = _choice(stored_value("appearance/theme"), RESULT_THEMES, legacy_theme)
        stored_accent_theme = stored_value("appearance/accent_theme")
        accent_theme = normalize_accent_theme(stored_accent_theme)
        stored_ring = stored_value("appearance/ring_color")
        ring = (
            normalize_hex_color(stored_ring)
            if isinstance(stored_ring, str)
            else RING_PRESETS[legacy_orb]
        )
        migrated_legacy_ring = (
            ring == LEGACY_DEFAULT_RING_COLOR and legacy_orb == "blue"
        )
        if migrated_legacy_ring:
            ring = DEFAULT_RING_COLOR
        stored_logo = stored_value("appearance/logo_path")
        logo = ""
        if isinstance(stored_logo, str) and read_logo_image(stored_logo) is not None:
            try:
                logo = str(Path(stored_logo).expanduser().resolve())
            except OSError:
                logo = ""
        recognition_mode = "mathcraft"
        stored_recognition_mode = stored_value("recognition/mode")
        stored_ai_base_url = stored_value("recognition/ai_base_url")
        stored_ai_model = stored_value("recognition/ai_model")
        ai_base_url, base_url_valid = _stored_ai_base_url(stored_ai_base_url)
        ai_model, model_valid = _stored_ai_model(stored_ai_model)
        ai_correction_enabled = _boolean(
            stored_value("recognition/ai_correction_enabled"), False
        )
        if ai_correction_enabled and not (base_url_valid and model_valid):
            ai_correction_enabled = False
        preferences = cls(
            recognition_mode=recognition_mode,
            orb_color=_preset_name(ring),
            result_theme=theme,
            show_settings_on_startup=_boolean(
                stored_value("window/show_settings_on_startup"), True
            ),
            ring_color=ring,
            logo_path=logo,
            ai_correction_enabled=ai_correction_enabled,
            ai_base_url=ai_base_url,
            ai_model=ai_model,
            auto_check_updates=_boolean(stored_value("updates/automatic"), True),
            accent_theme=accent_theme,
        )
        migrations: dict[str, object] = {}
        if stored_recognition_mode != recognition_mode:
            migrations["recognition/mode"] = recognition_mode
        if migrated_legacy_ring:
            migrations["appearance/ring_color"] = DEFAULT_RING_COLOR
            migrations["appearance/orb_color"] = "blue"
        if (
            stored_accent_theme is not None
            and str(stored_accent_theme).strip().lower() not in ACCENT_THEME_SWATCHES
        ):
            migrations["appearance/accent_theme"] = DEFAULT_ACCENT_THEME
        if _boolean(
            stored_value("recognition/ai_correction_enabled"), False
        ) and not ai_correction_enabled:
            migrations["recognition/ai_correction_enabled"] = False
        if migrations:
            with suppress(PreferencesSaveError):
                write_settings_values(settings, migrations)
        return preferences

    def save(self, settings: QSettings) -> QSettings:
        ring = self.effective_ring_color
        ai_base_url = ""
        ai_model = ""
        ai_config_valid = False
        if self.ai_base_url.strip() and self.ai_model.strip():
            try:
                ai_base_url = validate_ai_base_url(self.ai_base_url)
                ai_model = validate_ai_model_id(self.ai_model)
            except AICorrectionError:
                pass
            else:
                ai_config_valid = True
        elif self.ai_base_url.strip():
            try:
                ai_base_url = validate_ai_base_url(self.ai_base_url)
            except AICorrectionError:
                ai_base_url = ""
        ai_enabled = self.ai_correction_enabled and ai_config_valid
        values: dict[str, object] = {
                "recognition/mode": "mathcraft",
                "appearance/ring_color": ring,
                "appearance/theme": self.result_theme,
                "appearance/accent_theme": self.effective_accent_theme,
                "appearance/logo_path": self.effective_logo_path,
                "window/show_settings_on_startup": self.show_settings_on_startup,
                "recognition/ai_correction_enabled": ai_enabled,
                "recognition/ai_base_url": ai_base_url,
                "recognition/ai_model": ai_model,
                "updates/automatic": self.auto_check_updates,
                # Keep the V3 keys synchronized for downgrade compatibility.
                "appearance/orb_color": _preset_name(ring),
                "appearance/result_theme": self.result_theme,
        }
        if type(settings) is QSettings and settings.format() == QSettings.Format.IniFormat:
            return write_settings_values(settings, values)
        # Native stores do not offer a multi-key transaction. Persist a safe
        # disabled state first, then make the privacy-sensitive opt-in the last
        # isolated write so any earlier failure cannot enable network upload.
        values["recognition/ai_correction_enabled"] = False
        saved_settings = write_settings_values(settings, values)
        if ai_enabled:
            saved_settings = write_settings_values(
                saved_settings,
                {"recognition/ai_correction_enabled": True},
            )
        return saved_settings


def _preset_name(color: str) -> str:
    normalized = normalize_hex_color(color)
    return next((name for name, value in RING_PRESETS.items() if value == normalized), "blue")


def _stored_ai_base_url(value: object) -> tuple[str, bool]:
    if isinstance(value, str) and value.strip():
        try:
            return validate_ai_base_url(value), True
        except AICorrectionError:
            pass
    return "", False


def _stored_ai_model(value: object) -> tuple[str, bool]:
    if isinstance(value, str) and value.strip():
        try:
            return validate_ai_model_id(value), True
        except AICorrectionError:
            pass
    return "", False


def _choice(value: object, choices: tuple[str, ...], default: str) -> str:
    candidate = value if isinstance(value, str) else ""
    return candidate if candidate in choices else default


def _boolean(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _backend_is_available(key: str) -> bool:
    return any(
        backend_key == key and available
        for backend_key, _name, available in backend_summaries()
    )


class OrbAppearancePreview(QWidget):
    """Live rendering of the floating orb appearance controls."""

    def __init__(self) -> None:
        super().__init__()
        self._ring_color = DEFAULT_RING_COLOR
        self._logo = QImage()
        self.setFixedSize(104, 104)

    def set_appearance(self, ring_color: str, logo_path: str) -> None:
        self._ring_color = normalize_hex_color(ring_color)
        image = read_logo_image(logo_path, 42)
        self._logo = image if image is not None else QImage()
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = self.rect().adjusted(13, 13, -13, -13)
        painter.setPen(QPen(QColor(self._ring_color), 5))
        painter.setBrush(QColor("#151824"))
        painter.drawEllipse(circle)
        if not self._logo.isNull():
            target = self._logo.size().scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio)
            point = circle.center() - QPoint(target.width() // 2, target.height() // 2)
            painter.drawImage(point.x(), point.y(), self._logo)
        else:
            painter.setPen(QColor("#FFFFFF"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(17)
            painter.setFont(font)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, "fx")


class TutorialStepIllustration(QWidget):
    """Theme-aware vector diagram for one onboarding step."""

    def __init__(self, step_index: int) -> None:
        super().__init__()
        self.step_index = step_index
        self._formula_image = tutorial_formula_image()
        self.setObjectName("TutorialIllustration")
        self.setMinimumSize(220, 220)
        self.setMaximumWidth(320)
        self.setAccessibleName(f"使用方法第 {step_index + 1} 步图示")
        self.setAccessibleDescription(
            (
                "左键点击桌面悬浮球进入截图模式",
                "拖动箭头光标框选单个公式",
                "在结果面板核对电子公式和 LaTeX",
                "选择复制 LaTeX 或 MathML 并粘贴到 Word",
            )[step_index]
        )

    def paintEvent(self, event: object) -> None:  # noqa: N802
        super().paintEvent(event)  # type: ignore[arg-type]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        dark = QApplication.instance() is not None and (
            QApplication.instance().property("theme") == "dark"
        )
        colors = {
            "surface": QColor("#131620" if dark else "#FFFFFF"),
            "surface_alt": QColor("#191D29" if dark else "#F1F3F9"),
            "border": QColor("#3A4255" if dark else "#C7CEDD"),
            "text": QColor("#F1F3F8" if dark else "#171923"),
            "muted": QColor("#9AA3B5" if dark else "#64697A"),
            "accent": QColor(current_accent_color()),
            "success": QColor("#2DD4BF" if dark else "#0F8A78"),
        }
        area = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        if self.step_index == 0:
            self._draw_click_orb(painter, area, colors)
        elif self.step_index == 1:
            self._draw_selection(painter, area, colors)
        elif self.step_index == 2:
            self._draw_result(painter, area, colors)
        else:
            self._draw_copy_to_word(painter, area, colors)

    @staticmethod
    def _set_font(
        painter: QPainter, size: int, *, bold: bool = False, family: str = ""
    ) -> None:
        font = painter.font()
        font.setPointSize(size)
        font.setBold(bold)
        if family:
            font.setFamily(family)
        painter.setFont(font)

    @classmethod
    def _draw_label(
        cls,
        painter: QPainter,
        rect: QRectF,
        text: str,
        color: QColor,
        *,
        size: int = 9,
        bold: bool = False,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        family: str = "",
    ) -> None:
        painter.setPen(color)
        cls._set_font(painter, size, bold=bold, family=family)
        painter.drawText(rect, alignment, text)

    @staticmethod
    def _draw_card(
        painter: QPainter, rect: QRectF, fill: QColor, border: QColor, radius: float = 8
    ) -> None:
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

    @staticmethod
    def _draw_arrow_cursor(
        painter: QPainter, tip: QPoint, fill: QColor, outline: QColor
    ) -> None:
        points = QPolygon(
            [
                tip,
                tip + QPoint(1, 20),
                tip + QPoint(6, 15),
                tip + QPoint(11, 24),
                tip + QPoint(15, 22),
                tip + QPoint(10, 13),
                tip + QPoint(18, 13),
            ]
        )
        painter.setPen(QPen(outline, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(fill)
        painter.drawPolygon(points)

    def _draw_formula(self, painter: QPainter, rect: QRectF) -> None:
        if self._formula_image.isNull():
            self._draw_label(
                painter,
                rect,
                "Gaussian integral",
                QColor("#171923"),
                size=10,
                bold=True,
            )
            return
        source_size = self._formula_image.size()
        target_size = source_size.scaled(
            int(rect.width()),
            int(rect.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        target = QRectF(
            rect.center().x() - target_size.width() / 2,
            rect.center().y() - target_size.height() / 2,
            target_size.width(),
            target_size.height(),
        )
        painter.drawImage(target, self._formula_image)

    @classmethod
    def _draw_click_orb(
        cls, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        desktop = area.adjusted(4, 7, -4, -7)
        cls._draw_card(painter, desktop, colors["surface"], colors["border"])
        title_bottom = desktop.top() + 26
        painter.setPen(QPen(colors["border"], 1))
        painter.drawLine(
            QPoint(int(desktop.left()), int(title_bottom)),
            QPoint(int(desktop.right()), int(title_bottom)),
        )
        icon = QRectF(desktop.left() + 8, desktop.top() + 6, 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["accent"])
        painter.drawRoundedRect(icon, 4, 4)
        cls._draw_label(painter, icon, "fx", QColor("#FFFFFF"), size=5, bold=True)
        cls._draw_label(
            painter,
            QRectF(icon.right() + 6, desktop.top() + 4, desktop.width() - 94, 18),
            "论文公式.docx",
            colors["muted"],
            size=7,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        control_right = desktop.right() - 8
        painter.setPen(QPen(colors["muted"], 1))
        painter.drawLine(
            QPoint(int(control_right - 46), int(desktop.top() + 14)),
            QPoint(int(control_right - 38), int(desktop.top() + 14)),
        )
        painter.drawRect(
            QRectF(control_right - 27, desktop.top() + 10, 7, 7)
        )
        painter.drawLine(
            QPoint(int(control_right - 7), int(desktop.top() + 10)),
            QPoint(int(control_right), int(desktop.top() + 17)),
        )
        painter.drawLine(
            QPoint(int(control_right), int(desktop.top() + 10)),
            QPoint(int(control_right - 7), int(desktop.top() + 17)),
        )

        page = QRectF(
            desktop.left() + 14,
            title_bottom + 12,
            desktop.width() - 28,
            desktop.height() - 53,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F7F8FC"))
        painter.drawRoundedRect(page, 5, 5)
        painter.setPen(QPen(QColor("#DDE2EE"), 2))
        for index, ratio in enumerate((0.74, 0.58, 0.68, 0.42)):
            y = page.top() + 18 + index * 18
            painter.drawLine(
                QPoint(int(page.left() + 12), int(y)),
                QPoint(int(page.left() + 12 + (page.width() - 24) * ratio), int(y)),
            )

        orb_size = 52.0
        orb = QRectF(
            page.right() - orb_size - 12,
            page.bottom() - orb_size - 12,
            orb_size,
            orb_size,
        )
        painter.setPen(QPen(colors["accent"], 4))
        painter.setBrush(QColor("#151824"))
        painter.drawEllipse(orb)
        cls._draw_label(painter, orb, "fx", QColor("#FFFFFF"), size=14, bold=True)
        cls._draw_arrow_cursor(
            painter,
            QPoint(int(orb.left() - 27), int(orb.center().y() - 10)),
            colors["accent"],
            QColor("#FFFFFF"),
        )
        label_rect = QRectF(page.left() + 10, page.bottom() - 45, page.width() - 88, 25)
        cls._draw_label(
            painter,
            label_rect,
            "左键点击悬浮球",
            colors["accent"],
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_selection(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        page = area.adjusted(5, 4, -5, -4)
        self._draw_card(painter, page, QColor("#FFFFFF"), QColor("#DDE2EE"))
        painter.setPen(QPen(QColor("#DDE2EE"), 2))
        for index, ratio in enumerate((0.78, 0.61, 0.72, 0.51, 0.67)):
            y = page.top() + 20 + index * 31
            painter.drawLine(
                QPoint(int(page.left() + 14), int(y)),
                QPoint(int(page.left() + 14 + (page.width() - 28) * ratio), int(y)),
            )
        selection = QRectF(
            page.left() + 20,
            page.center().y() - 25,
            page.width() - 40,
            57,
        )
        painter.setPen(QPen(colors["accent"], 2, Qt.PenStyle.DashLine))
        accent_fill = QColor(colors["accent"])
        accent_fill.setAlpha(18)
        painter.setBrush(accent_fill)
        painter.drawRoundedRect(selection, 4, 4)
        self._draw_formula(painter, selection.adjusted(10, 8, -10, -8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors["accent"])
        for x, y in (
            (selection.left(), selection.top()),
            (selection.right(), selection.top()),
            (selection.left(), selection.bottom()),
            (selection.right(), selection.bottom()),
        ):
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))
        self._draw_arrow_cursor(
            painter,
            selection.bottomRight().toPoint() + QPoint(5, 5),
            colors["accent"],
            QColor("#FFFFFF"),
        )
        self._draw_label(
            painter,
            QRectF(page.left() + 12, page.bottom() - 31, page.width() - 24, 20),
            "松开鼠标后自动识别",
            colors["muted"],
            size=8,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_result(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        panel = area.adjusted(3, 6, -3, -6)
        self._draw_card(painter, panel, QColor("#10131B"), QColor("#2A3040"))
        self._draw_label(
            painter,
            QRectF(panel.left() + 13, panel.top() + 7, panel.width() - 26, 22),
            "公式识别结果",
            QColor("#F3F5FA"),
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        preview = QRectF(panel.left() + 13, panel.top() + 35, panel.width() - 26, 70)
        self._draw_card(painter, preview, QColor("#FFFFFF"), QColor("#DDE2EE"), 5)
        self._draw_formula(painter, preview.adjusted(13, 13, -13, -13))
        status = QRectF(panel.left() + 13, preview.bottom() + 7, 72, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#103A35"))
        painter.drawRoundedRect(status, 5, 5)
        self._draw_label(
            painter, status, "✓ 电子公式", QColor("#5EEAD4"), size=8, bold=True
        )
        latex = QRectF(panel.left() + 13, status.bottom() + 8, panel.width() - 26, 35)
        self._draw_card(painter, latex, QColor("#090B10"), QColor("#2A3040"), 5)
        latex_lines = TUTORIAL_FORMULA_LATEX.replace(
            r"\,\mathrm{d}x = ",
            r"\,\mathrm{d}x" "\n" "= ",
        )
        self._draw_label(
            painter,
            latex.adjusted(9, 2, -7, -2),
            latex_lines,
            QColor("#D6DAE7"),
            size=6,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            family="Consolas",
        )

    def _draw_copy_to_word(
        self, painter: QPainter, area: QRectF, colors: dict[str, QColor]
    ) -> None:
        button_gap = 8.0
        button_width = (area.width() - button_gap) / 2
        for index, text in enumerate(("复制 LaTeX", "复制 MathML")):
            button = QRectF(
                area.left() + index * (button_width + button_gap),
                area.top() + 7,
                button_width,
                34,
            )
            fill = colors["accent"] if index == 0 else colors["surface"]
            text_color = QColor("#FFFFFF") if index == 0 else colors["text"]
            button_border = colors["accent"] if index == 0 else colors["border"]
            self._draw_card(painter, button, fill, button_border, 6)
            self._draw_label(painter, button, text, text_color, size=8, bold=True)

        center_x = area.center().x()
        arrow_top = area.top() + 51
        arrow_bottom = area.top() + 78
        painter.setPen(QPen(colors["accent"], 2))
        painter.drawLine(
            QPoint(int(center_x), int(arrow_top)),
            QPoint(int(center_x), int(arrow_bottom)),
        )
        painter.drawLine(
            QPoint(int(center_x), int(arrow_bottom)),
            QPoint(int(center_x - 5), int(arrow_bottom - 6)),
        )
        painter.drawLine(
            QPoint(int(center_x), int(arrow_bottom)),
            QPoint(int(center_x + 5), int(arrow_bottom - 6)),
        )

        word = QRectF(area.left() + 13, area.top() + 87, area.width() - 26, area.height() - 96)
        self._draw_card(painter, word, colors["surface"], colors["border"])
        icon = QRectF(word.left() + 12, word.top() + 13, 32, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2B579A"))
        painter.drawRoundedRect(icon, 5, 5)
        self._draw_label(painter, icon, "W", QColor("#FFFFFF"), size=13, bold=True)
        self._draw_label(
            painter,
            QRectF(icon.right() + 9, word.top() + 10, word.width() - 62, 35),
            "Word 公式",
            colors["text"],
            size=9,
            bold=True,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        formula = QRectF(word.left() + 12, word.top() + 52, word.width() - 24, 36)
        painter.setPen(QPen(QColor("#DDE2EE"), 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(formula, 5, 5)
        self._draw_formula(painter, formula.adjusted(9, 8, -9, -8))
        self._draw_label(
            painter,
            QRectF(word.left() + 12, word.bottom() - 24, word.width() - 24, 17),
            "复制成功后面板自动收起",
            colors["success"],
            size=7,
            bold=True,
        )


class ToggleSwitch(QAbstractButton):
    """Compact, keyboard-accessible switch with an animated thumb."""

    def __init__(self) -> None:
        super().__init__()
        self._position = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(44, 24)
        self.setAccessibleName("启动时显示设置中心")
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = min(max(value, 0.0), 1.0)
        self.update()

    position = Property(float, get_position, set_position)

    @Slot(bool)
    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = QApplication.instance() is not None and (
            QApplication.instance().property("theme") == "dark"
        )
        accent = QColor(current_accent_color())
        inactive = QColor("#3A4255" if dark else "#C7CEDD")
        track = accent if self.isChecked() else inactive
        if not self.isEnabled():
            track.setAlpha(120)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(1, 1, 42, 22), 11, 11)
        x = 4.0 + self._position * 20.0
        thumb_color = "#FFFFFF" if self.isChecked() or not dark else "#131620"
        painter.setBrush(QColor(thumb_color))
        painter.drawEllipse(QRectF(x, 4, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(accent, 2))
            painter.drawRoundedRect(QRectF(0.5, 0.5, 43, 23), 12, 12)


class NavigationButton(QPushButton):
    """Sidebar button with a geometric marker and optional trailing hint."""

    def __init__(self, text: str, hint: str = "") -> None:
        super().__init__(text)
        self.marker = QLabel(self)
        self.marker.setObjectName("NavMarker")
        self.marker.setProperty("selected", "false")
        self.marker.setFixedSize(3, 18)
        self.marker.move(0, 10)
        self.marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if hint:
            trailing = QLabel(hint, self)
            trailing.setObjectName("NavHint")
            trailing.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            trailing.setGeometry(136, 0, 42, 38)
            trailing.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class ModeCard(QPushButton):
    """A whole-card radio choice that remains accessible from the keyboard."""

    selected = Signal(str)

    def __init__(
        self,
        key: str,
        title: str,
        tag: str,
        accessible_description: str,
    ) -> None:
        super().__init__()
        self.mode_key = key
        self.setObjectName("ModeCard")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{title}识别模式")
        self.setAccessibleDescription(accessible_description)
        self.setToolTip(accessible_description)
        self.setMinimumHeight(68)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(12)
        self.indicator = QLabel()
        self.indicator.setObjectName("ModeIndicator")
        self.indicator.setFixedSize(18, 18)
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("ModeTitle")
        tag_label = QLabel(tag)
        tag_label.setObjectName("ModeTag")
        title_row.addWidget(self.title_label)
        title_row.addWidget(tag_label)
        title_row.addStretch(1)
        for label in (
            self.indicator,
            self.title_label,
            tag_label,
        ):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        copy.addLayout(title_row)
        layout.addLayout(copy, 1)
        self.toggled.connect(self._sync_visual)
        self.clicked.connect(lambda: self.selected.emit(self.mode_key))
        self._sync_visual(False)

    @Slot(bool)
    def _sync_visual(self, checked: bool) -> None:
        value = "true" if checked else "false"
        self.setProperty("selected", value)
        self.indicator.setProperty("selected", value)
        self.indicator.setText("●" if checked else "")
        for widget in (self, self.indicator):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

class SettingsPanel(QWidget):
    start_requested = Signal()
    preferences_changed = Signal(object)
    session_preferences_changed = Signal(object)
    settings_backend_changed = Signal(object)
    ai_credential_changed = Signal()
    update_check_requested = Signal()

    _TUTORIAL_STEPS = (
        (
            "点击悬浮球",
            "点击悬浮球开始截图",
            "左键点击桌面上的 fx 悬浮球，然后拖动框选公式。",
            "截图只覆盖鼠标所在的那块屏幕；按 Esc 可随时取消。",
        ),
        (
            "框选公式",
            "拖动鼠标框住一个公式",
            "用矩形框住单个公式，松开鼠标后自动识别。",
            "一次只识别一个公式，不做正文 OCR、表格或整页版面识别。",
        ),
        (
            "核对结果",
            "核对排版后的电子公式",
            "对照原图核对电子公式，必要时直接修改 LaTeX。",
            "语法正确但数学含义错误的结果无法自动发现，仍需人工校对。",
        ),
        (
            "复制",
            "复制 LaTeX 或 MathML",
            "选择 LaTeX 或 MathML，复制成功后结果面板自动收起。",
            "直接粘贴到 Word、MathType 或其他支持 LaTeX / MathML 的编辑器。",
        ),
    )
    def __init__(
        self,
        settings: QSettings,
        preferences: FloatingPreferences,
        *,
        api_key_store: OpenAIApiKeyStore | None = None,
    ) -> None:
        super().__init__()
        self._api_key_store = api_key_store or OpenAIApiKeyStore()
        try:
            self._ai_key_present = bool(
                preferences.ai_base_url
                and self._api_key_store.has_key_for_base_url(
                    preferences.ai_base_url
                )
            )
            self._credential_error = ""
        except CredentialError as exc:
            self._ai_key_present = False
            self._credential_error = str(exc)
        if preferences.ai_correction_enabled and not self._ai_key_present:
            preferences = replace(preferences, ai_correction_enabled=False)
            with suppress(PreferencesSaveError):
                settings = preferences.save(settings)
        self._settings = settings
        self._preferences = preferences
        self._persisted_preferences = preferences
        self._settings_format_error = _settings_source_has_format_error(settings)
        self._save_failed = (
            self._settings_format_error
            or settings.status() != QSettings.Status.NoError
        )
        self._ai_model_worker: CompatibleModelWorker | None = None
        self._ai_active_context: tuple[str, str, str, int] | None = None
        self._ai_credential_generation = 0
        self._ai_models_base_url = preferences.ai_base_url if preferences.ai_model else ""
        self._building = True
        self._ring_color = preferences.effective_ring_color
        self._logo_path = preferences.effective_logo_path
        self.setObjectName("SettingsPanel")
        self.setWindowTitle("FormulaSnip 设置中心")
        self.setWindowIcon(application_icon())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.resize(1080, 700)
        self.setMinimumSize(960, 620)
        apply_application_theme(
            preferences.result_theme,
            preferences.effective_accent_theme,
        )
        self._build_ui()
        self._load_controls(preferences)
        self._building = False
        self._update_ai_draft_status()
        if self._save_failed:
            self._set_settings_error(
                "设置读取或保存失败，当前使用安全配置；请检查设置存储。"
            )

    @property
    def preferences(self) -> FloatingPreferences:
        return self._preferences

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = self._build_sidebar()
        outer.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.header = self._build_header()
        content_layout.addWidget(self.header)
        self.settings_error_label = QLabel()
        self.settings_error_label.setObjectName("SettingsErrorBanner")
        self.settings_error_label.setWordWrap(True)
        self.settings_error_label.setVisible(False)
        content_layout.addWidget(self.settings_error_label)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        self.settings_page = self._build_overview_page()
        self.recognition_page = self._build_recognition_page()
        self.appearance_page = self._build_appearance_page()
        self.tutorial_page = self._build_tutorial_page()
        for page in (
            self.settings_page,
            self.recognition_page,
            self.appearance_page,
            self.tutorial_page,
        ):
            self.pages.addWidget(page)
        content_layout.addWidget(self.pages, 1)
        outer.addWidget(content, 1)

        for index, (button, _title) in enumerate(self._nav_entries):
            button.clicked.connect(lambda _checked=False, target=index: self._select_page(target))
        self._select_page(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 22, 14, 14)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 0, 8, 22)
        brand_row.setSpacing(10)
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_logo.setFixedSize(30, 30)
        self._update_brand_logo()
        self.brand_logo.setAccessibleName("FormulaSnip 应用图标")
        title = QLabel("FormulaSnip")
        title.setObjectName("BrandTitle")
        self.brand_edition = QLabel(f"v{application_version()}", sidebar)
        self.brand_edition.setObjectName("BrandEdition")
        self.brand_edition.hide()
        brand_row.addWidget(self.brand_logo)
        brand_row.addWidget(title)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_entries: list[tuple[NavigationButton, str]] = []
        for label, title, hint, icon_name in (
            ("常规", "常规", "", "general"),
            ("识别", "识别", "", "recognition"),
            ("外观", "外观", "", "orb"),
            ("使用方法", "使用方法", "", "tutorial"),
        ):
            button = NavigationButton(label, hint)
            button.setObjectName("NavButton")
            button.setProperty("iconName", icon_name)
            button.setIconSize(QSize(19, 19))
            button.setCheckable(True)
            button.setFixedHeight(44)
            self.nav_group.addButton(button)
            self._nav_entries.append((button, title))
            layout.addWidget(button)
        layout.addStretch(1)
        self.github_button = QPushButton("loLollipop/FormulaSnip")
        self.github_button.setObjectName("GitHubLink")
        self.github_button.setFixedHeight(36)
        self.github_button.setIcon(
            github_mark_icon(
                "#9BA5B8" if self._preferences.result_theme == "dark" else "#697083"
            )
        )
        self.github_button.setIconSize(QSize(16, 16))
        self.github_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.github_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.github_button.setToolTip("打开 FormulaSnip GitHub 仓库")
        self.github_button.setAccessibleName("打开 FormulaSnip GitHub 仓库")
        self.github_button.clicked.connect(self._open_github_repository)
        layout.addWidget(self.github_button)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("SettingsHeader")
        header.setFixedHeight(66)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(28, 10, 28, 10)
        layout.setSpacing(10)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setObjectName("ThemeToggleButton")
        self.theme_toggle_button.setFixedSize(34, 34)
        self.theme_toggle_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.theme_toggle_button.setAccessibleName("切换明暗主题")
        self.theme_toggle_button.clicked.connect(self.toggle_theme)
        self.start_button = QPushButton("开始识别")
        self.start_button.setObjectName("SettingsPrimary")
        self.start_button.setFixedHeight(34)
        self.start_button.setMinimumWidth(104)
        self.start_button.clicked.connect(self.start_requested.emit)
        layout.addWidget(self.page_title)
        layout.addStretch(1)
        layout.addWidget(self.theme_toggle_button)
        layout.addWidget(self.start_button)
        return header

    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        body = QWidget()
        body.setObjectName("SettingsPageBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.addWidget(scroll)
        return shell, layout

    def _build_overview_page(self) -> QWidget:
        page, layout = self._page_shell()
        mode_card = _card("")
        mode_card.setObjectName("OverviewModeCard")
        mode_layout = mode_card.layout()
        assert mode_layout is not None
        mode_row = QHBoxLayout()
        mode_copy = QVBoxLayout()
        mode_copy.setSpacing(0)
        mode_title_row = QHBoxLayout()
        mode_title_row.setSpacing(9)
        self.overview_mode_name = QLabel()
        self.overview_mode_name.setObjectName("OverviewModeName")
        self.overview_mode_tag = QLabel()
        self.overview_mode_tag.setObjectName("ModeTag")
        mode_title_row.addWidget(self.overview_mode_name)
        mode_title_row.addWidget(self.overview_mode_tag)
        mode_title_row.addStretch(1)
        mode_copy.addLayout(mode_title_row)
        self.mode_summary_label = _muted_text("")
        self.mode_summary_label.hide()
        mode_row.addLayout(mode_copy, 1)
        mode_layout.addLayout(mode_row)
        layout.addWidget(mode_card)

        general = _card("应用与引擎")
        general_layout = general.layout()
        assert general_layout is not None
        startup_row = QWidget()
        startup_row.setObjectName("SettingsRow")
        startup_layout = QHBoxLayout(startup_row)
        startup_layout.setContentsMargins(0, 6, 0, 6)
        startup_copy = QVBoxLayout()
        startup_copy.setSpacing(0)
        startup_copy.addWidget(_row_title("启动时显示设置中心"))
        self.startup_checkbox = ToggleSwitch()
        self.startup_checkbox.toggled.connect(self._startup_toggle_changed)
        startup_layout.addLayout(startup_copy, 1)
        startup_layout.addWidget(self.startup_checkbox)
        general_layout.addWidget(startup_row)
        general_layout.addWidget(_divider())

        automatic_row = QHBoxLayout()
        automatic_row.addWidget(_row_title("自动检查更新"), 1)
        self.auto_update_toggle = ToggleSwitch()
        self.auto_update_toggle.setAccessibleName("自动检查更新")
        self.auto_update_toggle.toggled.connect(self._controls_changed)
        automatic_row.addWidget(self.auto_update_toggle)
        general_layout.addLayout(automatic_row)

        update_row = QWidget()
        update_row.setObjectName("SettingsRow")
        update_layout = QHBoxLayout(update_row)
        update_layout.setContentsMargins(0, 6, 0, 6)
        update_copy = QVBoxLayout()
        update_copy.setSpacing(3)
        self.update_version_label = _row_title(
            f"当前版本 v{application_version()}"
        )
        update_copy.addWidget(self.update_version_label)
        self.update_status_label = _muted_text("")
        self.update_status_label.hide()
        update_copy.addWidget(self.update_status_label)
        self.check_update_button = QPushButton("检查更新")
        self.update_button = self.check_update_button
        self.check_update_button.setObjectName("CompactButton")
        self.check_update_button.setFixedSize(96, 36)
        self.check_update_button.clicked.connect(self.update_check_requested.emit)
        update_layout.addLayout(update_copy, 1)
        update_layout.addWidget(self.check_update_button)
        general_layout.addWidget(update_row)
        general_layout.addWidget(_divider())

        summaries = backend_summaries()
        self.engine_status_labels: dict[str, QLabel] = {}
        self.engine_status_dots: dict[str, QLabel] = {}
        self._engine_available = {key: available for key, _name, available in summaries}
        for index, (key, name, available) in enumerate(summaries):
            row = QWidget()
            row.setObjectName("EngineRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 5, 0, 5)
            row_layout.setSpacing(12)
            badge = QLabel("MC")
            badge.setObjectName("EngineBadge")
            badge.setFixedSize(30, 30)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot = QLabel()
            dot.setObjectName("EngineDot")
            dot.setProperty("available", "false")
            dot.setFixedSize(6, 6)
            copy = QVBoxLayout()
            copy.setSpacing(0)
            copy.addWidget(_row_title(name))
            if available:
                detail = "本地模型 · CPU 推理 · 无需 API"
            else:
                detail = "安装缺失 · 请重新运行 uv sync"
            row.setToolTip(detail)
            status = QLabel("已安装 · 等待初始化" if available else "安装缺失")
            status.setObjectName("EngineStatus")
            status.setProperty("available", "false")
            self.engine_status_labels[key] = status
            self.engine_status_dots[key] = dot
            row_layout.addWidget(badge)
            row_layout.addLayout(copy, 1)
            status_row = QHBoxLayout()
            status_row.setContentsMargins(0, 0, 0, 0)
            status_row.setSpacing(6)
            status_row.addWidget(dot)
            status_row.addWidget(status)
            row_layout.addLayout(status_row)
            general_layout.addWidget(row)
            if index < len(summaries) - 1:
                general_layout.addWidget(_divider())
        layout.addWidget(general)
        layout.addStretch(1)
        return page

    def set_engine_status(self, key: str, state: str) -> None:
        """Update one engine's compact initialization status."""

        label = self.engine_status_labels.get(key)
        dot = self.engine_status_dots.get(key)
        if label is None or dot is None:
            return
        if not self._engine_available.get(key, False) or state == "missing":
            message = "安装缺失"
            ready = False
        else:
            messages = {
                "waiting": "已安装 · 等待初始化",
                "started": "正在初始化",
                "warming": "正在初始化",
                "succeeded": "已初始化",
                "ready": "已初始化",
                "failed": "初始化失败（识别时可重试）",
            }
            message = messages.get(state, state)
            ready = state in {"succeeded", "ready"}
        label.setText(message)
        available = "true" if ready else "false"
        label.setProperty("available", available)
        dot.setProperty("available", available)
        for widget in (label, dot):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _build_recognition_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.mode_combo = QComboBox()
        self.mode_combo.setVisible(False)
        mathcraft_available = _backend_is_available("mathcraft")
        mathcraft_label = "MathCraft OCR（CPU）"
        if not mathcraft_available:
            mathcraft_label += "（未安装）"
        self.mode_combo.addItem(mathcraft_label, "mathcraft")
        if not mathcraft_available:
            mathcraft_item = self.mode_combo.model().item(self.mode_combo.count() - 1)
            if mathcraft_item is not None:
                mathcraft_item.setEnabled(False)
        self.mode_combo.currentIndexChanged.connect(self._mode_combo_changed)
        layout.addWidget(self.mode_combo)

        modes = (
            (
                "mathcraft",
                "MathCraft OCR",
                "CPU" if mathcraft_available else "安装缺失",
                "本地单引擎公式识别；无需 API。"
                if mathcraft_available
                else "MathCraft 本地识别引擎未安装。",
            ),
        )
        self.mode_card_group = QButtonGroup(self)
        self.mode_card_group.setExclusive(True)
        self.mode_cards: dict[str, ModeCard] = {}
        for key, title, tag, description in modes:
            mode_card = ModeCard(key, title, tag, description)
            mode_card.setEnabled(key != "mathcraft" or mathcraft_available)
            mode_card.selected.connect(self._select_recognition_mode)
            self.mode_card_group.addButton(mode_card)
            self.mode_cards[key] = mode_card
            layout.addWidget(mode_card)

        ai_card = _card("")
        ai_layout = ai_card.layout()
        assert ai_layout is not None
        ai_header = QHBoxLayout()
        ai_title = _row_title("AI 辅助识别")
        ai_title.setToolTip("与 MathCraft 并行识别，结果不一致时可切换对照")
        ai_title.setAccessibleDescription(ai_title.toolTip())
        self.ai_correction_toggle = ToggleSwitch()
        self.ai_correction_toggle.setAccessibleName("启用 AI 智能并行")
        self.ai_correction_toggle.toggled.connect(self._ai_toggle_changed)
        ai_header.addWidget(ai_title, 1)
        ai_header.addWidget(self.ai_correction_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        ai_layout.addLayout(ai_header)

        self.ai_configuration_widget = QWidget()
        self.ai_configuration_widget.setObjectName("AiConfiguration")
        ai_configuration_layout = QVBoxLayout(self.ai_configuration_widget)
        ai_configuration_layout.setContentsMargins(0, 0, 0, 0)
        ai_configuration_layout.setSpacing(10)
        ai_configuration_layout.addWidget(_divider())

        ai_configuration_layout.addWidget(_field_label("兼容 API 地址"))
        self.ai_base_url_input = QLineEdit()
        self.ai_base_url_input.setObjectName("AiTextInput")
        self.ai_base_url_input.setPlaceholderText("输入 OpenAI 兼容 API 地址")
        self.ai_base_url_input.setClearButtonEnabled(True)
        self.ai_base_url_input.textChanged.connect(self._ai_base_url_changed)
        ai_configuration_layout.addWidget(self.ai_base_url_input)

        ai_configuration_layout.addWidget(_field_label("API Key"))
        key_row = QHBoxLayout()
        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setObjectName("ApiKeyInput")
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_input.setPlaceholderText(
            "已安全保存，可输入新 Key 替换"
            if self._ai_key_present
            else "输入兼容服务 API Key"
        )
        self.ai_api_key_input.setClearButtonEnabled(True)
        self.ai_api_key_input.textChanged.connect(
            lambda _text: self._update_ai_action_state()
        )
        self.ai_save_key_button = QPushButton("保存 Key")
        self.ai_save_key_button.setFixedHeight(36)
        self.ai_save_key_button.setEnabled(False)
        self.ai_save_key_button.clicked.connect(self._save_ai_api_key)
        self.ai_delete_key_button = QPushButton("删除")
        self.ai_delete_key_button.setFixedHeight(36)
        self.ai_delete_key_button.setEnabled(self._ai_key_present)
        self.ai_delete_key_button.clicked.connect(self._delete_ai_api_key)
        key_row.addWidget(self.ai_api_key_input, 1)
        key_row.addWidget(self.ai_save_key_button)
        key_row.addWidget(self.ai_delete_key_button)
        ai_configuration_layout.addLayout(key_row)
        self.ai_key_status_label = QLabel()
        self.ai_key_status_label.setObjectName("ApiKeyStatus")
        self.ai_key_status_label.setWordWrap(True)
        self._update_ai_key_status()
        ai_configuration_layout.addWidget(self.ai_key_status_label)

        ai_configuration_layout.addWidget(_field_label("模型"))
        model_row = QHBoxLayout()
        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setObjectName("AiModelCombo")
        self.ai_model_combo.setPlaceholderText("获取后选择模型")
        self.ai_model_combo.currentTextChanged.connect(self._ai_draft_changed)
        self.ai_refresh_models_button = QPushButton("获取模型")
        self.ai_refresh_models_button.setFixedHeight(36)
        self.ai_refresh_models_button.setEnabled(False)
        self.ai_refresh_models_button.clicked.connect(self._refresh_ai_models)
        self.ai_test_connection_button = QPushButton("测试连接")
        self.ai_test_connection_button.setFixedHeight(36)
        self.ai_test_connection_button.setEnabled(False)
        self.ai_test_connection_button.setToolTip(
            "发送一次小型视觉请求验证完整链路，可能产生少量费用"
        )
        self.ai_test_connection_button.clicked.connect(self._test_ai_connection)
        model_row.addWidget(self.ai_model_combo, 1)
        model_row.addWidget(self.ai_refresh_models_button)
        model_row.addWidget(self.ai_test_connection_button)
        ai_configuration_layout.addLayout(model_row)
        self.ai_connection_status_label = QLabel("填写地址并保存 Key")
        self.ai_connection_status_label.setObjectName("AiConnectionStatus")
        self.ai_connection_status_label.setWordWrap(True)
        ai_configuration_layout.addWidget(self.ai_connection_status_label)
        self.ai_privacy_label = _muted_text("框选图像将发送到所配 API，并可能产生费用。")
        privacy_detail = (
            "AI 默认关闭。启用后仅上传当前框选图像，不上传本地识别结果；"
            "兼容 API 服务商可能收取费用。"
        )
        self.ai_privacy_label.setWordWrap(True)
        self.ai_privacy_label.setToolTip(privacy_detail)
        self.ai_privacy_label.setAccessibleDescription(privacy_detail)
        ai_configuration_layout.addWidget(self.ai_privacy_label)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.ai_save_config_button = QPushButton("保存配置")
        self.ai_save_config_button.setObjectName("SettingsPrimary")
        self.ai_save_config_button.setFixedHeight(38)
        self.ai_save_config_button.setMinimumWidth(112)
        self.ai_save_config_button.setEnabled(False)
        self.ai_save_config_button.clicked.connect(self._save_ai_configuration)
        save_row.addWidget(self.ai_save_config_button)
        ai_configuration_layout.addLayout(save_row)
        ai_layout.addWidget(self.ai_configuration_widget)
        layout.addWidget(ai_card)

        layout.addStretch(1)
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._page_shell()
        row = QHBoxLayout()
        row.setSpacing(12)
        preview_card = _card("")
        preview_layout = preview_card.layout()
        assert preview_layout is not None
        stage = QWidget()
        stage.setObjectName("OrbPreviewStage")
        stage.setFixedHeight(210)
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(20, 16, 20, 12)
        self.orb_preview = OrbAppearancePreview()
        stage_layout.addWidget(self.orb_preview, 0, Qt.AlignmentFlag.AlignCenter)
        self.ring_hex_label = QLabel(self._ring_color)
        self.ring_hex_label.setObjectName("RingHexLabel")
        stage_layout.addWidget(
            self.ring_hex_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        )
        preview_layout.addWidget(stage)
        row.addWidget(preview_card, 5)

        controls = _card("")
        controls_layout = controls.layout()
        assert controls_layout is not None
        controls_layout.addWidget(_field_label("界面主题色"))
        theme_swatches = QHBoxLayout()
        theme_swatches.setSpacing(10)
        self.theme_color_group = QButtonGroup(self)
        self.theme_color_group.setExclusive(True)
        self.theme_color_buttons: dict[str, QPushButton] = {}
        for name, color in ACCENT_THEME_SWATCHES.items():
            button = QPushButton()
            button.setObjectName("ThemeSwatchButton")
            button.setCheckable(True)
            button.setFixedSize(34, 34)
            button.setProperty("accentTheme", name)
            button.setToolTip(THEME_ACCENT_LABELS[name])
            button.setAccessibleName(f"界面主题色：{THEME_ACCENT_LABELS[name]}")
            button.setStyleSheet(f"QPushButton {{ background: {color}; }}")
            self.theme_color_group.addButton(button)
            self.theme_color_buttons[name] = button
            theme_swatches.addWidget(button)
        theme_swatches.addStretch(1)
        controls_layout.addLayout(theme_swatches)
        controls_layout.addWidget(_divider())
        controls_layout.addWidget(_field_label("圆环颜色"))
        swatches = QHBoxLayout()
        swatches.setSpacing(10)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        self.color_buttons: dict[str, QPushButton] = {}
        for name, color in RING_PRESETS.items():
            button = QPushButton()
            button.setObjectName("SwatchButton")
            button.setCheckable(True)
            button.setFixedSize(34, 34)
            button.setProperty("ringColor", color)
            button.setToolTip(color)
            button.setAccessibleName(f"圆环颜色：{RING_PRESET_LABELS[name]}（{color}）")
            button.setStyleSheet(f"QPushButton {{ background: {color}; }}")
            self.color_group.addButton(button)
            self.color_buttons[name] = button
            swatches.addWidget(button)
        self.custom_color_button = QPushButton("+")
        self.custom_color_button.setObjectName("CustomColorButton")
        self.custom_color_button.setFixedSize(34, 34)
        self.custom_color_button.setToolTip("从系统颜色盘选择")
        self.custom_color_button.setAccessibleName("从系统颜色盘选择圆环颜色")
        self.custom_color_button.clicked.connect(self.choose_ring_color)
        swatches.addWidget(self.custom_color_button)
        swatches.addStretch(1)
        controls_layout.addLayout(swatches)
        controls_layout.addWidget(_divider())
        controls_layout.addWidget(_field_label("中心 Logo"))
        logo_row = QHBoxLayout()
        self.upload_logo_button = QPushButton("上传图片…")
        self.restore_logo_button = QPushButton("恢复默认")
        self.upload_logo_button.setFixedHeight(36)
        self.restore_logo_button.setFixedHeight(36)
        self.upload_logo_button.clicked.connect(self.choose_logo)
        self.upload_logo_button.setToolTip(
            "PNG / JPG / WebP / BMP，最大 12 MB"
        )
        self.restore_logo_button.clicked.connect(self.restore_default_logo)
        logo_row.addWidget(self.upload_logo_button)
        logo_row.addWidget(self.restore_logo_button)
        controls_layout.addLayout(logo_row)
        self.logo_status_label = QLabel("")
        self.logo_status_label.setObjectName("MutedText")
        self.logo_status_label.setWordWrap(True)
        self.logo_status_label.hide()
        controls_layout.addWidget(self.logo_status_label)
        row.addWidget(controls, 6)
        layout.addLayout(row)
        layout.addStretch(1)
        self.theme_color_group.buttonClicked.connect(self._accent_theme_selected)
        self.color_group.buttonClicked.connect(self._preset_color_selected)
        return page

    def _build_tutorial_page(self) -> QWidget:
        page, layout = self._page_shell()
        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.tutorial_step_buttons: list[QPushButton] = []
        for step_index, step_data in enumerate(self._TUTORIAL_STEPS):
            step_button = QPushButton(f"{step_index + 1:02d}  {step_data[0]}")
            step_button.setObjectName("TutorialStepButton")
            step_button.setFixedHeight(38)
            step_button.setToolTip(step_data[3])
            step_button.setAccessibleDescription(f"{step_data[2]} {step_data[3]}")
            step_button.clicked.connect(
                lambda _checked=False, target=step_index: self._set_tutorial_step(target)
            )
            self.tutorial_step_buttons.append(step_button)
            progress.addWidget(step_button, 1)
        layout.addLayout(progress)

        self.tutorial_stack = QStackedWidget()
        self.tutorial_stack.setObjectName("TutorialStack")
        self.tutorial_stack.setMinimumHeight(300)
        self.tutorial_counters: list[QLabel] = []
        self.tutorial_illustrations: list[TutorialStepIllustration] = []
        for step_index, (_label, heading, body, tip) in enumerate(
            self._TUTORIAL_STEPS
        ):
            step = QWidget()
            step_layout = QHBoxLayout(step)
            step_layout.setContentsMargins(28, 22, 28, 22)
            step_layout.setSpacing(24)
            copy = QVBoxLayout()
            copy.setSpacing(0)
            counter = QLabel(f"步骤 {step_index + 1} / 4")
            counter.setObjectName("TutorialCounter")
            self.tutorial_counters.append(counter)
            heading_label = QLabel(heading)
            heading_label.setObjectName("TutorialHeading")
            body_label = QLabel(body)
            body_label.setObjectName("TutorialBody")
            body_label.setWordWrap(True)
            step.setToolTip(tip)
            step.setAccessibleDescription(f"{body} {tip}")
            heading_label.setToolTip(tip)
            body_label.setToolTip(tip)
            counter.hide()
            copy.addWidget(heading_label)
            copy.addSpacing(12)
            copy.addWidget(body_label)
            copy.addStretch(1)
            illustration = TutorialStepIllustration(step_index)
            illustration.setToolTip(tip)
            self.tutorial_illustrations.append(illustration)
            step_layout.addLayout(copy, 3)
            step_layout.addWidget(illustration, 2)
            self.tutorial_stack.addWidget(step)
        self.tutorial_counter = self.tutorial_counters[0]
        layout.addWidget(self.tutorial_stack)
        nav = QHBoxLayout()
        self.tutorial_back_button = QPushButton("上一步")
        self.tutorial_next_button = QPushButton("下一步")
        self.tutorial_next_button.setObjectName("SettingsPrimary")
        self.tutorial_start_button = QPushButton("开始识别公式")
        self.tutorial_start_button.setObjectName("SettingsPrimary")
        for button in (
            self.tutorial_back_button,
            self.tutorial_next_button,
            self.tutorial_start_button,
        ):
            button.setFixedHeight(36)
        nav.addWidget(self.tutorial_back_button)
        nav.addStretch(1)
        nav.addWidget(self.tutorial_next_button)
        nav.addWidget(self.tutorial_start_button)
        layout.addLayout(nav)
        layout.addStretch(1)
        self.tutorial_back_button.clicked.connect(self.previous_tutorial_step)
        self.tutorial_next_button.clicked.connect(self.next_tutorial_step)
        self.tutorial_start_button.clicked.connect(self.start_requested.emit)
        self._update_tutorial_controls()
        return page

    def _load_controls(self, preferences: FloatingPreferences) -> None:
        mode_index = self.mode_combo.findData(preferences.recognition_mode)
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        self._sync_mode_cards()
        self.ai_correction_toggle.setChecked(
            preferences.ai_correction_enabled and self._ai_key_present
        )
        self.ai_correction_toggle.set_position(
            1.0 if self.ai_correction_toggle.isChecked() else 0.0
        )
        self.ai_base_url_input.setText(preferences.ai_base_url)
        self.ai_model_combo.clear()
        if preferences.ai_model:
            self.ai_model_combo.addItem(preferences.ai_model)
            self.ai_model_combo.setCurrentIndex(0)
        else:
            self.ai_model_combo.setCurrentIndex(-1)
        self.ai_configuration_widget.setVisible(
            self.ai_correction_toggle.isChecked()
        )
        self._update_ai_action_state()
        self.startup_checkbox.setChecked(preferences.show_settings_on_startup)
        self.auto_update_toggle.setChecked(preferences.auto_check_updates)
        self.startup_checkbox.set_position(
            1.0 if preferences.show_settings_on_startup else 0.0
        )
        self.auto_update_toggle.set_position(
            1.0 if preferences.auto_check_updates else 0.0
        )
        self._startup_toggle_changed(self.startup_checkbox.isChecked())
        self._ring_color = preferences.effective_ring_color
        selected = _preset_name(self._ring_color)
        if RING_PRESETS.get(selected) == self._ring_color:
            self.color_buttons[selected].setChecked(True)
        self._logo_path = preferences.effective_logo_path
        selected_accent = preferences.effective_accent_theme
        self.theme_color_buttons[selected_accent].setChecked(True)
        self._update_appearance_preview()
        self._update_theme_button()

    def _select_page(self, index: int) -> None:
        bounded = min(max(index, 0), self.pages.count() - 1)
        self.pages.setCurrentIndex(bounded)
        button, title = self._nav_entries[bounded]
        button.setChecked(True)
        for nav_button, _nav_title in self._nav_entries:
            selected = nav_button is button
            nav_button.marker.setProperty(
                "selected", "true" if selected else "false"
            )
            nav_button.marker.style().unpolish(nav_button.marker)
            nav_button.marker.style().polish(nav_button.marker)
            nav_button.setIcon(
                line_icon(
                    str(nav_button.property("iconName")),
                    self._navigation_icon_color(selected=selected),
                )
            )
        self.page_title.setText(title)

    @Slot()
    def _open_github_repository(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/loLollipop/FormulaSnip"))

    @Slot(str)
    def _select_recognition_mode(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        item = self.mode_combo.model().item(index) if index >= 0 else None
        if index < 0 or (item is not None and not item.isEnabled()):
            self._sync_mode_cards()
            return
        self.mode_combo.setCurrentIndex(index)

    @Slot()
    def _mode_combo_changed(self) -> None:
        self._sync_mode_cards()
        self._controls_changed()

    def _sync_mode_cards(self) -> None:
        selected = str(self.mode_combo.currentData())
        for key, card in self.mode_cards.items():
            card.setChecked(key == selected)
        summary = (
            "MathCraft OCR",
            "CPU" if self._engine_available.get("mathcraft", False) else "安装缺失",
            "本地单引擎公式识别",
        )
        name, tag, meta = summary
        self.overview_mode_name.setText(name)
        self.overview_mode_tag.setText(tag)
        self.mode_summary_label.setText(meta)

    @Slot()
    def _controls_changed(self) -> None:
        if self._building:
            return
        self._preferences = replace(
            self._preferences,
            recognition_mode="mathcraft",
            orb_color=_preset_name(self._ring_color),
            show_settings_on_startup=self.startup_checkbox.isChecked(),
            ring_color=self._ring_color,
            logo_path=self._logo_path,
            auto_check_updates=self.auto_update_toggle.isChecked(),
        )
        self._save_preferences()

    def _save_preferences(self) -> bool:
        previous_settings = self._settings
        try:
            self._settings = self._preferences.save(self._settings)
        except PreferencesSaveError as exc:
            self._save_failed = True
            self._settings_format_error = (
                self._settings_format_error
                or exc.format_error
                or _settings_source_has_format_error(self._settings)
            )
            self._set_settings_error(SETTINGS_ERROR_MESSAGE)
            self._set_ai_connection_status(SETTINGS_ERROR_MESSAGE, error=True)
            # Keep disabling AI effective during storage failure, without
            # claiming these changes were persisted.
            session_preferences = replace(self._preferences, ai_correction_enabled=False)
            self._preferences = session_preferences
            ai_blocker = QSignalBlocker(self.ai_correction_toggle)
            self.ai_correction_toggle.setChecked(False)
            del ai_blocker
            self.ai_configuration_widget.hide()
            self.ai_correction_toggle.setAccessibleDescription("已关闭")
            if (
                not self._settings_format_error
                and not (
                    type(self._settings) is QSettings
                    and self._settings.format() == QSettings.Format.IniFormat
                )
            ):
                # QSettings retains values queued before a failed sync. Replace
                # the sensitive opt-in in that shared cache before permissions
                # can recover and a later sync/destructor flushes it to disk.
                self._settings.setValue("recognition/ai_correction_enabled", False)
                self._settings.sync()
            self.session_preferences_changed.emit(session_preferences)
            return False
        self._save_failed = False
        self._settings_format_error = False
        self._set_settings_error("")
        self._persisted_preferences = self._preferences
        if self._settings is not previous_settings:
            self.settings_backend_changed.emit(self._settings)
        self.preferences_changed.emit(self._preferences)
        return True

    def _set_settings_error(self, message: str) -> None:
        self.settings_error_label.setText(message)
        self.settings_error_label.setVisible(bool(message.strip()))

    def adopt_settings_backend(self, settings: QSettings) -> None:
        """Share a healthy backend produced by another atomic settings write."""

        if self._settings_format_error or settings.status() != QSettings.Status.NoError:
            return
        self._settings = settings
        self._save_failed = False

    @Slot(bool)
    def _ai_toggle_changed(self, checked: bool) -> None:
        self.ai_configuration_widget.setVisible(checked)
        self.ai_correction_toggle.setAccessibleDescription(
            "已开启" if checked else "已关闭"
        )
        if not checked:
            self.cancel_ai_request()
            if self._preferences.ai_correction_enabled:
                self._preferences = replace(
                    self._preferences, ai_correction_enabled=False
                )
                if not self._save_preferences():
                    return
            self._set_ai_connection_status("AI 辅助已关闭")
        else:
            self._update_ai_draft_status()
        self._update_ai_action_state()

    @Slot(str)
    def _ai_base_url_changed(self, _text: str) -> None:
        if self._building:
            return
        self._disable_active_ai_for_changed_provider()
        request_was_active = self._ai_model_worker is not None
        self._ai_request_configuration_changed()
        self._refresh_ai_key_presence()
        current_base_url = self.ai_base_url_input.text().strip().rstrip("/")
        if self._ai_models_base_url and current_base_url != self._ai_models_base_url:
            blocker = QSignalBlocker(self.ai_model_combo)
            self.ai_model_combo.clear()
            self.ai_model_combo.setCurrentIndex(-1)
            del blocker
            self._ai_models_base_url = ""
            message = "地址已更改，请重新获取模型"
            if request_was_active:
                message = "地址已更改，已取消旧请求，请重新获取模型"
            self._set_ai_connection_status(message)
        elif not request_was_active:
            self._update_ai_draft_status()
        self._update_ai_action_state()

    def _disable_active_ai_for_changed_provider(self) -> bool:
        """Keep a draft provider from inheriting the active provider's credentials."""

        if not self._preferences.ai_correction_enabled:
            return False
        active_base_url = self._preferences.ai_base_url.strip().rstrip("/")
        draft_base_url = self.ai_base_url_input.text().strip().rstrip("/")
        if draft_base_url == active_base_url:
            return False
        self._preferences = replace(self._preferences, ai_correction_enabled=False)
        self._save_preferences()
        return True

    @Slot()
    def _ai_draft_changed(self) -> None:
        if self._building:
            return
        request_was_active = self._ai_model_worker is not None
        self._ai_request_configuration_changed()
        self._update_ai_action_state()
        if not request_was_active:
            self._update_ai_draft_status()

    def _ai_draft_is_dirty(self) -> bool:
        return (
            self.ai_correction_toggle.isChecked()
            != self._preferences.ai_correction_enabled
            or self.ai_base_url_input.text().strip()
            != self._preferences.ai_base_url
            or self.ai_model_combo.currentText().strip()
            != self._preferences.ai_model
        )

    def _update_ai_draft_status(self) -> None:
        if self._building or not self.ai_correction_toggle.isChecked():
            return
        if self._save_failed:
            self._set_ai_connection_status(SETTINGS_ERROR_MESSAGE, error=True)
            return
        raw_base_url = self.ai_base_url_input.text().strip()
        raw_model = self.ai_model_combo.currentText().strip()
        if self._credential_error:
            self._set_ai_connection_status(self._credential_error, error=True)
        elif not raw_base_url:
            self._set_ai_connection_status("请输入兼容 API 地址")
        elif not self._ai_key_present:
            self._set_ai_connection_status("请为当前地址保存 Key")
        elif not raw_model:
            self._set_ai_connection_status("获取并选择模型")
        elif self._ai_draft_is_dirty():
            self._set_ai_connection_status("配置已更改，请保存后生效")
        else:
            self._set_ai_connection_status("配置已保存并生效")

    def _update_ai_action_state(self) -> None:
        visible = self.ai_correction_toggle.isChecked()
        idle = self._ai_model_worker is None
        try:
            validate_ai_base_url(self.ai_base_url_input.text())
        except AICorrectionError:
            base_url_valid = False
        else:
            base_url_valid = True
        try:
            validate_ai_model_id(self.ai_model_combo.currentText())
        except AICorrectionError:
            model_valid = False
        else:
            model_valid = True
        self.ai_save_key_button.setEnabled(
            visible
            and idle
            and base_url_valid
            and bool(self.ai_api_key_input.text().strip())
        )
        self.ai_delete_key_button.setEnabled(visible and idle and self._ai_key_present)
        self.ai_model_combo.setEnabled(visible and idle)
        self.ai_refresh_models_button.setEnabled(
            visible and idle and self._ai_key_present and base_url_valid
        )
        self.ai_test_connection_button.setEnabled(
            visible
            and idle
            and self._ai_key_present
            and base_url_valid
            and model_valid
        )
        has_complete_draft = bool(
            self.ai_base_url_input.text().strip()
            and self.ai_model_combo.currentText().strip()
        )
        self.ai_save_config_button.setEnabled(
            visible
            and idle
            and self._ai_key_present
            and has_complete_draft
            and self._ai_draft_is_dirty()
        )

    @Slot()
    def _ai_request_configuration_changed(self) -> None:
        if (
            self._building
            or self._ai_model_worker is None
            or self._ai_request_is_current()
        ):
            return
        self.cancel_ai_request()
        self._set_ai_connection_status("配置已变化，已取消旧请求")

    @Slot(bool)
    def _startup_toggle_changed(self, checked: bool) -> None:
        self.startup_checkbox.setAccessibleDescription(
            "已开启" if checked else "已关闭"
        )
        self._controls_changed()

    @Slot()
    def _save_ai_configuration(self) -> None:
        if self._ai_model_worker is not None:
            return
        try:
            ai_base_url = validate_ai_base_url(self.ai_base_url_input.text())
            ai_model = validate_ai_model_id(self.ai_model_combo.currentText())
        except AICorrectionError as exc:
            self._set_ai_connection_status(str(exc), error=True)
            self._update_ai_action_state()
            return
        try:
            self._ai_key_present = self._api_key_store.has_key_for_base_url(
                ai_base_url
            )
        except CredentialError as exc:
            self._credential_error = str(exc)
            self._set_ai_connection_status(str(exc), error=True)
            self._update_ai_key_status()
            self._update_ai_action_state()
            return
        if not self._ai_key_present:
            self._set_ai_connection_status("请为当前地址保存 Key", error=True)
            self._update_ai_action_state()
            return

        base_url_blocker = QSignalBlocker(self.ai_base_url_input)
        model_blocker = QSignalBlocker(self.ai_model_combo)
        self.ai_base_url_input.setText(ai_base_url)
        model_index = self.ai_model_combo.findText(ai_model)
        if model_index >= 0:
            self.ai_model_combo.setCurrentIndex(model_index)
        del model_blocker
        del base_url_blocker
        self._ai_models_base_url = ai_base_url
        self._preferences = replace(
            self._preferences,
            ai_correction_enabled=True,
            ai_base_url=ai_base_url,
            ai_model=ai_model,
        )
        if not self._save_preferences():
            self._update_ai_action_state()
            return
        self._set_ai_connection_status("配置已保存并生效")
        self._update_ai_action_state()

    @Slot()
    def _save_ai_api_key(self) -> None:
        try:
            base_url = validate_ai_base_url(self.ai_base_url_input.text())
        except AICorrectionError as exc:
            self._set_ai_connection_status(str(exc), error=True)
            self._update_ai_action_state()
            return
        try:
            self._api_key_store.save(self.ai_api_key_input.text(), base_url)
        except CredentialError as exc:
            self._credential_error = str(exc)
            self._update_ai_key_status()
            return
        self._disable_active_ai_for_changed_provider()
        self.cancel_ai_request()
        self._ai_credential_generation += 1
        self.ai_api_key_input.clear()
        self._credential_error = ""
        self._ai_key_present = True
        self.ai_api_key_input.setPlaceholderText("已安全保存，可输入新 Key 替换")
        self._update_ai_key_status()
        self._update_ai_action_state()
        self.ai_credential_changed.emit()
        self._update_ai_draft_status()

    @Slot()
    def _delete_ai_api_key(self) -> None:
        try:
            self._api_key_store.delete()
        except CredentialError as exc:
            self._credential_error = str(exc)
            self._update_ai_key_status()
            return
        self.cancel_ai_request()
        self._ai_credential_generation += 1
        self._credential_error = ""
        self._ai_key_present = False
        self.ai_correction_toggle.setChecked(False)
        self.ai_api_key_input.clear()
        self.ai_api_key_input.setPlaceholderText("输入兼容服务 API Key")
        self._set_ai_connection_status("填写地址并保存 Key")
        self._update_ai_key_status()
        self._update_ai_action_state()
        self.ai_credential_changed.emit()

    @Slot()
    def _refresh_ai_models(self) -> None:
        self._start_ai_model_request("list")

    @Slot()
    def _test_ai_connection(self) -> None:
        self._start_ai_model_request("test")

    def _start_ai_model_request(self, action: str) -> None:
        if self._ai_model_worker is not None:
            return
        try:
            base_url = validate_ai_base_url(self.ai_base_url_input.text())
        except AICorrectionError as exc:
            self._set_ai_connection_status(str(exc), error=True)
            return
        model = ""
        if action == "test":
            try:
                model = validate_ai_model_id(self.ai_model_combo.currentText())
            except AICorrectionError as exc:
                self._set_ai_connection_status(str(exc), error=True)
                return
        try:
            api_key = self._api_key_store.load_for_base_url(base_url)
        except CredentialError as exc:
            self._set_ai_connection_status(str(exc), error=True)
            return
        if api_key is None:
            self._ai_key_present = False
            self._set_ai_connection_status("请为当前地址保存 Key", error=True)
            self._update_ai_key_status()
            self._update_ai_action_state()
            return
        worker = CompatibleModelWorker(
            action,
            api_key,
            base_url,
            model,
        )
        worker.signals.succeeded.connect(self._ai_model_request_succeeded)
        worker.signals.failed.connect(self._ai_model_request_failed)
        worker.signals.finished.connect(self._ai_model_request_finished)
        self._ai_model_worker = worker
        self._ai_active_context = (
            action,
            base_url,
            model,
            self._ai_credential_generation,
        )
        self._update_ai_action_state()
        self._set_ai_connection_status(
            "正在拉取上游模型…" if action == "list" else "正在测试连接…"
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(object, object)
    def _ai_model_request_succeeded(
        self, worker: CompatibleModelWorker, result: object
    ) -> None:
        if not self._ai_request_is_current(worker):
            return
        if worker.action == "list" and isinstance(result, tuple):
            current = self.ai_model_combo.currentText().strip()
            blocker = QSignalBlocker(self.ai_model_combo)
            self.ai_model_combo.clear()
            for model in result:
                self.ai_model_combo.addItem(str(model))
            index = self.ai_model_combo.findText(current)
            self.ai_model_combo.setCurrentIndex(index)
            del blocker
            self._ai_models_base_url = worker.base_url
            self._update_ai_action_state()
            self._set_ai_connection_status(f"已获取 {len(result)} 个模型，请选择")
        elif worker.action == "test" and isinstance(result, str):
            self._set_ai_connection_status(f"连接成功，可访问 {result}")

    @Slot(object, str)
    def _ai_model_request_failed(
        self, worker: CompatibleModelWorker, message: str
    ) -> None:
        if not self._ai_request_is_current(worker):
            return
        self._set_ai_connection_status(message, error=True)

    @Slot(object)
    def _ai_model_request_finished(self, worker: CompatibleModelWorker) -> None:
        if worker is not self._ai_model_worker:
            return
        self._ai_model_worker = None
        self._ai_active_context = None
        self._update_ai_action_state()

    def cancel_ai_request(self) -> None:
        worker = self._ai_model_worker
        if worker is None:
            return
        worker.cancel()
        self._ai_model_worker = None
        self._ai_active_context = None
        self._update_ai_action_state()

    def _ai_request_is_current(
        self, worker: CompatibleModelWorker | None = None
    ) -> bool:
        context = self._ai_active_context
        if context is None:
            return False
        action, base_url, model, generation = context
        current_worker = self._ai_model_worker
        if worker is None:
            worker = current_worker
        if worker is None or worker is not current_worker or worker.action != action:
            return False
        try:
            current_base_url = validate_ai_base_url(self.ai_base_url_input.text())
            current_model = (
                ""
                if action == "list"
                else validate_ai_model_id(self.ai_model_combo.currentText())
            )
        except AICorrectionError:
            return False
        return (
            base_url == current_base_url
            and model == current_model
            and generation == self._ai_credential_generation
        )

    def _set_ai_connection_status(self, message: str, *, error: bool = False) -> None:
        self.ai_connection_status_label.setText(message)
        self.ai_connection_status_label.setProperty("error", error)
        if self.ai_connection_status_label.style() is not None:
            self.ai_connection_status_label.style().unpolish(
                self.ai_connection_status_label
            )
            self.ai_connection_status_label.style().polish(
                self.ai_connection_status_label
            )

    def _update_ai_key_status(self) -> None:
        if self._credential_error:
            self.ai_key_status_label.setText(self._credential_error)
            self.ai_key_status_label.setProperty("error", True)
            self.ai_key_status_label.setProperty("saved", False)
        elif self._ai_key_present:
            self.ai_key_status_label.setText(
                "当前地址的 API Key 已保存到 Windows 凭据管理器"
            )
            self.ai_key_status_label.setProperty("error", False)
            self.ai_key_status_label.setProperty("saved", True)
        else:
            self.ai_key_status_label.setText("未配置 API Key")
            self.ai_key_status_label.setProperty("error", False)
            self.ai_key_status_label.setProperty("saved", False)
        if self.ai_key_status_label.style() is not None:
            self.ai_key_status_label.style().unpolish(self.ai_key_status_label)
            self.ai_key_status_label.style().polish(self.ai_key_status_label)

    def _refresh_ai_key_presence(self) -> None:
        try:
            base_url = validate_ai_base_url(self.ai_base_url_input.text())
        except AICorrectionError:
            self._ai_key_present = False
            return
        try:
            self._ai_key_present = self._api_key_store.has_key_for_base_url(base_url)
            self._credential_error = ""
        except CredentialError as exc:
            self._ai_key_present = False
            self._credential_error = str(exc)
        self._update_ai_key_status()

    @Slot()
    def toggle_theme(self) -> None:
        next_theme = "light" if self._preferences.result_theme == "dark" else "dark"
        self._preferences = replace(
            self._preferences,
            result_theme=next_theme,
            ring_color=self._ring_color,
            logo_path=self._logo_path,
        )
        apply_application_theme(
            next_theme,
            self._preferences.effective_accent_theme,
        )
        self._update_theme_button()
        if not self._building:
            self._save_preferences()

    def _update_theme_button(self) -> None:
        self._update_brand_logo()
        if self._preferences.result_theme == "dark":
            self.theme_toggle_button.setText("")
            self.theme_toggle_button.setIcon(line_icon("sun", "#9BA5B8"))
            self.theme_toggle_button.setToolTip("切换到浅色主题")
            self.theme_toggle_button.setAccessibleDescription(
                "当前为深色主题，按下切换到浅色主题"
            )
        else:
            self.theme_toggle_button.setText("")
            self.theme_toggle_button.setIcon(line_icon("moon", "#697083"))
            self.theme_toggle_button.setToolTip("切换到深色主题")
            self.theme_toggle_button.setAccessibleDescription(
                "当前为浅色主题，按下切换到深色主题"
            )
        self.github_button.setIcon(
            github_mark_icon(
                "#9BA5B8" if self._preferences.result_theme == "dark" else "#697083"
            )
        )
        self.theme_toggle_button.setIconSize(QSize(17, 17))
        self._update_navigation_icons()

    def _update_brand_logo(self) -> None:
        accent = theme_accent_color(
            self._preferences.result_theme,
            self._preferences.effective_accent_theme,
        )
        self.brand_logo.setPixmap(themed_brand_pixmap(accent, 30))

    def _navigation_icon_color(self, *, selected: bool) -> str:
        dark = self._preferences.result_theme == "dark"
        if selected:
            return theme_accent_color(
                self._preferences.result_theme,
                self._preferences.effective_accent_theme,
            )
        return "#9BA5B8" if dark else "#697083"

    def _update_navigation_icons(self) -> None:
        for button, _title in self._nav_entries:
            button.setIcon(
                line_icon(
                    str(button.property("iconName")),
                    self._navigation_icon_color(selected=button.isChecked()),
                )
            )

    @Slot()
    def _accent_theme_selected(self) -> None:
        checked = self.theme_color_group.checkedButton()
        if checked is None:
            return
        accent_theme = normalize_accent_theme(checked.property("accentTheme"))
        if accent_theme == self._preferences.effective_accent_theme:
            return
        self._preferences = replace(self._preferences, accent_theme=accent_theme)
        apply_application_theme(self._preferences.result_theme, accent_theme)
        self._update_theme_button()
        for toggle in self.findChildren(ToggleSwitch):
            toggle.update()
        for illustration in self.tutorial_illustrations:
            illustration.update()
        if not self._building:
            self._save_preferences()

    @Slot()
    def _preset_color_selected(self) -> None:
        checked = self.color_group.checkedButton()
        if checked is None:
            return
        self._ring_color = normalize_hex_color(checked.property("ringColor"))
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def choose_ring_color(self) -> None:
        selected = QColorDialog.getColor(QColor(self._ring_color), self, "选择悬浮球圆环颜色")
        if not selected.isValid():
            return
        self._ring_color = normalize_hex_color(selected.name(QColor.NameFormat.HexRgb))
        matching = _preset_name(self._ring_color)
        if RING_PRESETS.get(matching) == self._ring_color:
            self.color_buttons[matching].setChecked(True)
        else:
            self.color_group.setExclusive(False)
            checked = self.color_group.checkedButton()
            if checked is not None:
                checked.setChecked(False)
            self.color_group.setExclusive(True)
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def choose_logo(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择悬浮球 Logo",
            str(Path(self._logo_path).parent) if self._logo_path else "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        image = read_logo_image(path)
        if image is None:
            self.logo_status_label.setText("图片无效或格式不匹配，已保留原 Logo。")
            self.logo_status_label.show()
            return
        else:
            self._logo_path = str(Path(path).resolve())
            self.logo_status_label.setText(Path(path).name)
            self.logo_status_label.show()
        self._update_appearance_preview()
        self._controls_changed()

    @Slot()
    def restore_default_logo(self) -> None:
        if not self._logo_path:
            return
        self._logo_path = ""
        self.logo_status_label.clear()
        self.logo_status_label.hide()
        self._update_appearance_preview()
        self._controls_changed()

    def _update_appearance_preview(self) -> None:
        self.orb_preview.set_appearance(self._ring_color, self._logo_path)
        self.ring_hex_label.setText(self._ring_color)
        if not self._logo_path:
            self.logo_status_label.clear()
            self.logo_status_label.hide()
        else:
            self.logo_status_label.setText(Path(self._logo_path).name)
            self.logo_status_label.show()

    @Slot()
    def show_tutorial(self) -> None:
        self.tutorial_stack.setCurrentIndex(0)
        self._select_page(3)
        self._update_tutorial_controls()

    @Slot()
    def next_tutorial_step(self) -> None:
        index = min(self.tutorial_stack.count() - 1, self.tutorial_stack.currentIndex() + 1)
        self._set_tutorial_step(index)

    @Slot()
    def previous_tutorial_step(self) -> None:
        if self.tutorial_stack.currentIndex() == 0:
            self._select_page(0)
            return
        self._set_tutorial_step(self.tutorial_stack.currentIndex() - 1)

    def _set_tutorial_step(self, index: int) -> None:
        bounded = min(max(index, 0), self.tutorial_stack.count() - 1)
        self.tutorial_stack.setCurrentIndex(bounded)
        self._update_tutorial_controls()

    def show_settings_page(self) -> None:
        self._select_page(0)

    def show_appearance_page(self) -> None:
        self._select_page(2)

    def show_recognition_page(self) -> None:
        self._select_page(1)

    def set_update_status(self, message: str, *, checking: bool = False) -> None:
        self.update_status_label.setText(message)
        self.update_status_label.setVisible(bool(message.strip()))
        self.check_update_button.setEnabled(not checking)

    def _update_tutorial_controls(self) -> None:
        index = self.tutorial_stack.currentIndex()
        last = index == self.tutorial_stack.count() - 1
        self.tutorial_counter = self.tutorial_counters[index]
        for step_index, button in enumerate(self.tutorial_step_buttons):
            state = "current" if step_index == index else (
                "complete" if step_index < index else "pending"
            )
            button.setProperty("stepState", state)
            button.style().unpolish(button)
            button.style().polish(button)
        self.tutorial_back_button.setText("返回常规" if index == 0 else "上一步")
        self.tutorial_next_button.setVisible(not last)
        self.tutorial_start_button.setVisible(last)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.start_requested.emit()
        event.accept()


def _card(title: str, description: str = "") -> QWidget:
    card = QWidget()
    card.setObjectName("SettingsCard")
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(12)
    if title:
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
    if description:
        detail = QLabel(description)
        detail.setObjectName("CardDescription")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return card


def _divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("CardDivider")
    divider.setFrameShape(QFrame.Shape.HLine)
    return divider


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SettingsFieldLabel")
    return label


def _row_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("RowTitle")
    return label


def _muted_text(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedText")
    return label
