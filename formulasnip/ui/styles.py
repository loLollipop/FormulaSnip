from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def application_stylesheet(theme: str) -> str:
    """Return the complete application stylesheet for the selected theme."""
    light = theme == "light"
    colors = {
        "window": "#f3f6fb" if light else "#0d1320",
        "surface": "#ffffff" if light else "#121b2b",
        "surface_alt": "#f7f9fc" if light else "#172235",
        "surface_hover": "#edf2f9" if light else "#202e45",
        "sidebar": "#e9eef6" if light else "#0a101c",
        "text": "#172033" if light else "#edf3fb",
        "muted": "#60708a" if light else "#98a8bf",
        "border": "#d7dfeb" if light else "#2b3b54",
        "accent": "#315fdd" if light else "#5d83f3",
        "accent_hover": "#244ec2" if light else "#7598ff",
        "accent_pressed": "#1d3fa8" if light else "#426be0",
        "accent_soft": "#e8efff" if light else "#1b2d55",
        "code": "#f7f9fc" if light else "#09101d",
        "success": "#19704f" if light else "#72dfb5",
        "warning": "#9a5800" if light else "#fbbf24",
    }
    return f"""
QWidget {{
    color: {colors['text']};
    font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}}
QWidget#SettingsPanel {{ background: {colors['window']}; }}
QDialog#UpdateDialog {{ background: {colors['surface']}; }}
QPlainTextEdit#UpdateNotes {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 9px;
    padding: 10px; selection-background-color: {colors['accent']};
}}
QProgressBar {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 7px;
    min-height: 16px; text-align: center;
}}
QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 6px; }}
QWidget#SettingsSidebar {{
    background: {colors['sidebar']};
    border-right: 1px solid {colors['border']};
}}
QWidget#SettingsHeader {{
    background: {colors['surface']};
    border-bottom: 1px solid {colors['border']};
}}
QLabel#BrandLogo {{ background: transparent; border: none; }}
QLabel#BrandTitle {{ font-size: 17px; font-weight: 700; }}
QLabel#BrandEdition, QLabel#PageSubtitle, QLabel#SettingsHint,
QLabel#CardDescription, QLabel#TutorialCounter, QLabel#MutedText,
QLabel#LogoSafetyText {{ color: {colors['muted']}; }}
QLabel#BrandEdition {{ font-size: 11px; }}
QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#PageSubtitle {{ font-size: 12px; }}
QLabel#CardTitle, QLabel#SettingsFieldLabel, QLabel#RowTitle {{
    font-size: 15px; font-weight: 700;
}}
QLabel#OfflineCard {{
    background: {colors['surface']}; color: {colors['muted']};
    border: 1px solid {colors['border']}; border-radius: 10px;
    padding: 11px; font-size: 11px;
}}
QWidget#SettingsCard, QStackedWidget#TutorialStack {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QFrame#CardDivider {{
    border: none; border-top: 1px solid {colors['border']};
    max-height: 1px;
}}
QWidget#SettingsCTA {{
    background: {colors['accent_soft']};
    border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QWidget#OrbPreviewStage {{
    background: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QLabel#EngineDot {{
    background: {colors['muted']}; border-radius: 4px;
}}
QLabel#EngineDot[available="true"] {{ background: {colors['success']}; }}
QLabel#EngineStatus {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-radius: 6px; padding: 5px 10px; font-size: 12px;
}}
QLabel#EngineStatus[available="true"] {{
    color: {colors['accent']}; background: {colors['accent_soft']};
}}
QPushButton {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{
    background: {colors['surface_hover']}; border-color: {colors['accent']};
}}
QPushButton:focus {{ border: 2px solid {colors['accent']}; }}
QPushButton:pressed {{
    background: {colors['surface_hover']}; border-color: {colors['accent']};
}}
QPushButton:disabled {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-color: {colors['border']};
}}
QPushButton#NavButton {{
    background: transparent; border: none; color: {colors['muted']};
    border-radius: 9px; padding: 10px 12px 10px 31px; text-align: left;
    font-weight: 500;
}}
QPushButton#NavButton:hover {{
    background: {colors['surface_hover']}; color: {colors['text']};
}}
QPushButton#NavButton:checked {{
    background: {colors['accent_soft']}; color: {colors['accent']}; font-weight: 700;
}}
QLabel#NavMarker {{ background: {colors['muted']}; border-radius: 2px; }}
QPushButton#NavButton:checked QLabel#NavMarker {{ background: {colors['accent']}; }}
QLabel#NavHint {{ color: {colors['muted']}; font-size: 11px; background: transparent; }}
QPushButton#SettingsPrimary, QPushButton#FloatingPrimary {{
    background: {colors['accent']}; border-color: {colors['accent']}; color: white;
}}
QPushButton#SettingsPrimary:hover, QPushButton#FloatingPrimary:hover {{
    background: {colors['accent_hover']}; border-color: {colors['accent_hover']};
}}
QPushButton#SettingsPrimary:pressed, QPushButton#FloatingPrimary:pressed {{
    background: {colors['accent_pressed']}; border-color: {colors['accent_pressed']};
}}
QPushButton#ModeCard {{
    background: {colors['surface']}; border: 1px solid {colors['border']};
    border-radius: 12px; padding: 0; text-align: left; min-height: 116px;
}}
QPushButton#ModeCard:hover, QPushButton#ModeCard:focus {{
    border: 2px solid {colors['accent']};
}}
QPushButton#ModeCard[selected="true"] {{
    background: {colors['accent_soft']}; border: 2px solid {colors['accent']};
}}
QPushButton#ModeCard:disabled {{ background: {colors['surface_alt']}; }}
QLabel#ModeIndicator {{
    border: 2px solid {colors['border']}; border-radius: 10px;
    color: {colors['accent']}; font-size: 11px;
}}
QLabel#ModeIndicator[selected="true"] {{ border-color: {colors['accent']}; }}
QLabel#ModeTitle {{ font-size: 15px; font-weight: 700; background: transparent; }}
QLabel#ModeTag {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-radius: 5px; padding: 3px 8px; font-size: 11px; font-weight: 600;
}}
QLabel#ModeBody {{ color: {colors['muted']}; font-size: 13px; background: transparent; }}
QLabel#ModeMeta {{ color: {colors['muted']}; font-size: 11px; background: transparent; }}
QLabel#TriggerTag {{
    background: {colors['surface_alt']}; border: 1px solid {colors['border']};
    border-radius: 7px; padding: 6px 10px; font-size: 12px;
}}
QPushButton#TutorialStepButton {{
    background: transparent; color: {colors['muted']};
    border: none; border-top: 4px solid {colors['border']};
    border-radius: 2px; padding: 7px 2px 0; text-align: left; font-size: 12px;
}}
QPushButton#TutorialStepButton[stepState="complete"],
QPushButton#TutorialStepButton[stepState="current"] {{
    border-top-color: {colors['accent']};
}}
QPushButton#TutorialStepButton[stepState="current"] {{
    color: {colors['accent']}; font-weight: 700;
}}
QPushButton#TutorialStepButton:hover {{ color: {colors['text']}; }}
QLabel#TutorialHeading {{ font-size: 23px; font-weight: 700; }}
QLabel#TutorialBody {{ color: {colors['muted']}; font-size: 14px; }}
QLabel#TutorialTip {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border: 1px solid {colors['border']}; border-radius: 9px;
    padding: 11px 13px; font-size: 12px;
}}
QWidget#TutorialIllustration {{
    background: {colors['surface_alt']};
    border: 1px solid {colors['border']}; border-radius: 10px;
}}
QPushButton#SwatchButton {{ padding: 5px; border-radius: 10px; }}
QPushButton#SwatchButton:checked {{ border: 3px solid {colors['accent']}; }}
QPushButton#IconButton {{
    background: transparent; color: {colors['muted']}; border: none;
    border-radius: 6px; padding: 0; font-size: 20px;
}}
QPushButton#IconButton:hover {{ background: {colors['surface_hover']}; }}
QComboBox {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 8px 11px; min-width: 220px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {colors['accent']}; }}
QComboBox QAbstractItemView {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; selection-background-color: {colors['accent']};
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QWidget#FloatingResultPanel {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 10px;
}}
QLabel#FloatingResultTitle {{ color: {colors['text']}; font-size: 16px; font-weight: 700; }}
QLabel#FloatingMeta {{ color: {colors['accent']}; font-size: 12px; }}
QStackedWidget#FloatingPreviewStack, QWidget#FloatingPreviewFrame,
QLabel#FloatingPreviewMessage {{
    background: #ffffff; color: #334155; border: 1px solid #d8e0eb;
    border-radius: 8px;
}}
QWidget#FloatingPreviewFrame QWidget#FloatingSvgPreview {{ background: transparent; border: none; }}
QLabel#FloatingQuality {{ color: {colors['success']}; font-size: 12px; }}
QLabel#FloatingQuality[warning="true"] {{ color: {colors['warning']}; }}
QPlainTextEdit#FloatingLatex {{
    background: {colors['code']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 7px; font-family: Consolas, monospace; font-size: 12px;
}}
QLabel#FloatingStatus {{ color: {colors['success']}; min-height: 18px; }}
QMenu {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; padding: 6px;
}}
QMenu::item {{ padding: 9px 24px 9px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {colors['accent']}; color: white; }}
QToolTip {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; padding: 5px;
}}
"""


def apply_application_theme(theme: str) -> str:
    """Apply theme to every application-owned surface, including menus."""
    normalized = "light" if theme == "light" else "dark"
    application = QApplication.instance()
    if application is None:
        return normalized
    application.setProperty("theme", normalized)
    application.setStyleSheet(application_stylesheet(normalized))
    palette = QPalette()
    palette.setColor(
        QPalette.ColorRole.Window, QColor("#f3f6fb" if normalized == "light" else "#0d1320")
    )
    palette.setColor(
        QPalette.ColorRole.WindowText,
        QColor("#172033" if normalized == "light" else "#edf3fb"),
    )
    palette.setColor(
        QPalette.ColorRole.Base, QColor("#ffffff" if normalized == "light" else "#121b2b")
    )
    palette.setColor(
        QPalette.ColorRole.Text, QColor("#172033" if normalized == "light" else "#edf3fb")
    )
    application.setPalette(palette)
    return normalized


APP_STYLESHEET = application_stylesheet("dark")
