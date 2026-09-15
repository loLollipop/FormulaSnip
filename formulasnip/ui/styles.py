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
        "accent_soft": "#e8efff" if light else "#1b2d55",
        "code": "#f7f9fc" if light else "#09101d",
        "success": "#19704f" if light else "#72dfb5",
        "warning": "#9a5800" if light else "#fbbf24",
    }
    return f"""
QWidget {{
    color: {colors['text']}; font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}}
QWidget#SettingsPanel {{ background: {colors['window']}; }}
QWidget#SettingsSidebar {{
    background: {colors['sidebar']}; border-right: 1px solid {colors['border']};
}}
QWidget#SettingsHeader {{
    background: {colors['surface']}; border-bottom: 1px solid {colors['border']};
}}
QLabel#BrandMark {{
    background: {colors['accent']}; color: white; border-radius: 11px;
    font-size: 16px; font-weight: 800;
}}
QLabel#BrandTitle {{ font-size: 19px; font-weight: 750; }}
  QLabel#SettingsHint, QLabel#CardDescription,
QLabel#TutorialCounter, QLabel#MutedText {{ color: {colors['muted']}; }}
  QLabel#PageTitle {{ font-size: 22px; font-weight: 750; }}
QLabel#SectionTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#CardTitle, QLabel#SettingsFieldLabel, QLabel#TutorialTitle {{
    font-size: 15px; font-weight: 700;
}}
QLabel#TutorialBody {{ color: {colors['muted']}; font-size: 14px; }}
QWidget#SettingsCard, QWidget#TutorialCard, QStackedWidget#TutorialStack {{
    background: {colors['surface']}; border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QWidget#OrbPreviewStage {{
    background: {colors['surface_alt']}; border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QPushButton {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {colors['surface_hover']}; border-color: {colors['accent']}; }}
QPushButton:pressed {{ padding-top: 9px; padding-bottom: 7px; }}
QPushButton:disabled {{ color: {colors['muted']}; background: {colors['surface_alt']}; }}
QPushButton#NavButton {{
    background: transparent; border: none; color: {colors['muted']};
    border-radius: 8px; padding: 10px 14px; text-align: left;
}}
QPushButton#NavButton:hover {{ background: {colors['surface_hover']}; color: {colors['text']}; }}
    QPushButton#NavButton:checked {{
        background: {colors['accent_soft']}; color: {colors['accent']}; font-weight: 700;
    }}
    QPushButton#ToggleButton {{ text-align: left; max-width: 240px; }}
    QPushButton#ToggleButton:checked {{
        background: {colors['accent_soft']}; border-color: {colors['accent']};
        color: {colors['accent']};
    }}
QPushButton#SettingsPrimary, QPushButton#FloatingPrimary {{
    background: {colors['accent']}; border-color: {colors['accent']}; color: white;
}}
QPushButton#SettingsPrimary:hover, QPushButton#FloatingPrimary:hover {{
    background: {colors['accent_hover']}; border-color: {colors['accent_hover']};
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
QCheckBox {{ color: {colors['text']}; spacing: 9px; }}
QCheckBox::indicator {{ width: 19px; height: 19px; }}
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
