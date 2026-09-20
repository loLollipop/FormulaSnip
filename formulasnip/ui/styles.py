from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def application_stylesheet(theme: str) -> str:
    """Return the complete application stylesheet for the selected theme."""
    light = theme == "light"
    colors = {
        "window": "#f6f7f9" if light else "#0f1218",
        "surface": "#ffffff" if light else "#161a21",
        "surface_alt": "#f4f6f9" if light else "#1c212a",
        "surface_hover": "#e9edf3" if light else "#222832",
        "sidebar": "#eef0f4" if light else "#0c0f14",
        "text": "#151a21" if light else "#e8ecf3",
        "muted": "#5f6a79" if light else "#98a8bf",
        "border": "#e1e5ec" if light else "#262d38",
        "border_strong": "#c8cfda" if light else "#39414f",
        "accent": "#315fdd" if light else "#8fa4ff",
        "accent_primary": "#315fdd" if light else "#4f6ed4",
        "accent_hover": "#244ec2" if light else "#4262c9",
        "accent_pressed": "#1d3fa8" if light else "#3653b5",
        "accent_soft": "#edf0fd" if light else "#1a2131",
        "code": "#f4f6f9" if light else "#11151c",
        "success": "#1c7a56" if light else "#5fd3a3",
        "warning": "#9a5800" if light else "#fbbf24",
    }
    settings = {
        "window": "#F7F8FA" if light else "#101318",
        "surface": "#FFFFFF" if light else "#181C23",
        "sidebar": "#FBFCFE" if light else "#14181F",
        "border": "#E4E8EE" if light else "#29313D",
        "text": "#1B2430" if light else "#F1F5F9",
        "muted": "#667085" if light else "#98A2B3",
        "accent": "#2563EB" if light else "#86A5FF",
        "accent_soft": "#E8EFFF" if light else "#1D2940",
        "accent_hover": "#1D4ED8" if light else "#9BB5FF",
        "accent_text": "#FFFFFF" if light else "#101318",
        "hover": "#F1F4F8" if light else "#202630",
        "input": "#FFFFFF" if light else "#14181F",
    }
    return f"""
QWidget {{
    color: {colors['text']};
    font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}}
QWidget#SettingsPanel, QWidget#SettingsPanel QWidget {{
    color: {settings['text']};
    font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}}
QWidget#SettingsPanel {{ background: {settings['window']}; }}
QDialog#UpdateDialog {{ background: {colors['surface']}; }}
QFrame#UpdateHeader {{
    background: {colors['surface']};
    border: none; border-bottom: 1px solid {colors['border']};
}}
QLabel#UpdateAppIcon {{
    background: {colors['accent_soft']}; border: 1px solid {colors['border']};
    border-radius: 12px;
}}
QLabel#UpdateTitle {{ font-size: 20px; font-weight: 650; }}
QLabel#UpdateSubtitle {{ color: {colors['muted']}; font-size: 12px; }}
QWidget#UpdateContent {{ background: {colors['surface']}; }}
QScrollArea#UpdateContentScroll,
QScrollArea#UpdateContentScroll > QWidget > QWidget {{
    background: {colors['surface']};
    border: none;
}}
QFrame#UpdateVersionCard {{
    background: {colors['surface_alt']}; border: 1px solid {colors['border']};
    border-radius: 11px;
}}
QLabel#UpdateVersionCaption {{ color: {colors['muted']}; font-size: 11px; }}
QLabel#UpdateCurrentVersion, QLabel#UpdateLatestVersion {{
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 19px; font-weight: 650;
}}
QLabel#UpdateCurrentVersion {{ color: {colors['muted']}; }}
QLabel#UpdateLatestVersion {{ color: {colors['accent']}; }}
QLabel#UpdateVersionArrow {{ color: {colors['muted']}; font-size: 20px; }}
QLabel#UpdateSectionTitle {{ font-size: 13px; font-weight: 650; }}
QTextBrowser#UpdateNotes {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 10px;
    padding: 8px; selection-background-color: {colors['accent']};
}}
QTextBrowser#UpdateNotes QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 4px 2px 4px 0;
}}
QTextBrowser#UpdateNotes QScrollBar::handle:vertical {{
    background: {colors['border_strong']}; min-height: 28px; border-radius: 4px;
}}
QTextBrowser#UpdateNotes QScrollBar::handle:vertical:hover {{
    background: {colors['muted']};
}}
QTextBrowser#UpdateNotes QScrollBar::add-line:vertical,
QTextBrowser#UpdateNotes QScrollBar::sub-line:vertical {{ height: 0; }}
QTextBrowser#UpdateNotes QScrollBar::add-page:vertical,
QTextBrowser#UpdateNotes QScrollBar::sub-page:vertical {{ background: transparent; }}
QLabel#UpdateMetaChip {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border: 1px solid {colors['border']}; border-radius: 7px;
    padding: 4px 9px; font-size: 11px;
}}
QFrame#UpdateStatusPanel {{
    background: {colors['accent_soft']}; border: 1px solid {colors['border']};
    border-radius: 9px;
}}
QFrame#UpdateStatusPanel[state="error"] {{
    background: {colors['surface_alt']}; border-color: {colors['warning']};
}}
QLabel#UpdateStatusLabel {{ background: transparent; font-size: 12px; }}
QFrame#UpdateStatusPanel[state="error"] QLabel#UpdateStatusLabel {{
    color: {colors['warning']};
}}
QLabel#UpdateProgressDetail {{
    color: {colors['muted']}; background: transparent;
    font-family: "Segoe UI", sans-serif; font-size: 11px;
}}
QProgressBar#UpdateProgress {{
    min-height: 6px; max-height: 6px; background: {colors['surface_hover']};
    border: none; border-radius: 3px;
}}
QProgressBar#UpdateProgress::chunk {{
    background: {colors['accent_primary']}; border-radius: 3px;
}}
QFrame#UpdateFooter {{
    background: {colors['surface_alt']};
    border: none; border-top: 1px solid {colors['border']};
}}
QProgressBar {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 7px;
    min-height: 16px; text-align: center;
}}
QProgressBar::chunk {{ background: {colors['accent']}; border-radius: 6px; }}
QWidget#SettingsSidebar {{
    background: {settings['sidebar']};
    border-right: 1px solid {settings['border']};
}}
QWidget#SettingsHeader {{
    background: {settings['window']};
    border-bottom: 1px solid {settings['border']};
}}
QLabel#BrandLogo {{ background: transparent; border: none; }}
QLabel#BrandTitle {{ font-size: 16px; font-weight: 600; }}
QLabel#BrandEdition, QLabel#PageSubtitle, QLabel#SettingsHint,
QLabel#CardDescription, QLabel#TutorialCounter, QLabel#MutedText,
QLabel#LogoSafetyText {{ color: {settings['muted']}; }}
QLabel#BrandEdition {{ font-size: 11px; }}
QLabel#PageTitle {{ font-size: 21px; font-weight: 600; }}
QLabel#PageSubtitle {{ font-size: 12px; }}
QLabel#CardTitle, QLabel#SettingsFieldLabel, QLabel#RowTitle {{
    font-size: 14px; font-weight: 600;
}}
QLabel#OfflineCard {{
    background: {settings['surface']}; color: {settings['muted']};
    border: 1px solid {settings['border']}; border-radius: 10px;
    padding: 11px; font-size: 11px;
}}
QWidget#SettingsCard, QWidget#OverviewModeCard, QWidget#RecognitionTriggerCard,
QStackedWidget#TutorialStack {{
    background: {settings['surface']};
    border: 1px solid {settings['border']};
    border-radius: 11px;
}}
QFrame#CardDivider {{
    border: none; border-top: 1px solid {settings['border']};
    max-height: 1px;
}}
QWidget#SettingsCTA {{
    background: {settings['accent_soft']};
    border: 1px solid {settings['border']};
    border-radius: 12px;
}}
QWidget#OrbPreviewStage {{
    background: {settings['sidebar']};
    border: 1px solid {settings['border']};
    border-radius: 12px;
}}
QLabel#RingHexLabel {{
    color: {settings['muted']}; background: transparent;
    font-family: Consolas, monospace; font-size: 11px;
}}
QLabel#OverviewModeName {{ font-size: 24px; font-weight: 700; }}
QLabel#EngineBadge {{
    color: {settings['accent']}; background: {settings['accent_soft']};
    border-radius: 8px; font-family: Consolas, monospace; font-size: 11px;
}}
QLabel#EngineDot {{
    background: {settings['muted']}; border-radius: 4px;
}}
QLabel#EngineDot[available="true"] {{ background: {colors['success']}; }}
QLabel#EngineStatus {{
    color: {settings['muted']}; background: transparent;
    padding: 4px 8px; font-size: 12px;
}}
QLabel#EngineStatus[available="true"] {{
    color: {colors['success']};
}}
QWidget#SettingsPanel QLineEdit#ApiKeyInput,
QWidget#SettingsPanel QLineEdit#AiTextInput,
QWidget#SettingsPanel QComboBox#AiModelCombo {{
    background: {settings['input']}; color: {settings['text']};
    border: 1px solid {settings['border']}; border-radius: 8px;
    padding: 8px 11px; min-height: 18px;
}}
QWidget#SettingsPanel QLineEdit#ApiKeyInput:focus,
QWidget#SettingsPanel QLineEdit#AiTextInput:focus,
QWidget#SettingsPanel QComboBox#AiModelCombo:focus {{
    border: 1px solid {settings['accent']};
}}
QLabel#ApiKeyStatus {{ color: {settings['muted']}; font-size: 12px; }}
QLabel#ApiKeyStatus[saved="true"] {{ color: {colors['success']}; }}
QLabel#ApiKeyStatus[error="true"] {{ color: {colors['warning']}; }}
QLabel#AiConnectionStatus {{ color: {settings['muted']}; font-size: 12px; }}
QLabel#AiConnectionStatus[error="true"] {{ color: {colors['warning']}; }}
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
QWidget#SettingsPanel QPushButton {{
    background: {settings['surface']}; color: {settings['text']};
    border: 1px solid {settings['border']}; border-radius: 8px;
    padding: 8px 14px; font-weight: 500;
}}
QWidget#SettingsPanel QPushButton:hover {{
    background: {settings['hover']}; border-color: {settings['accent']};
}}
QWidget#SettingsPanel QPushButton:focus {{ border: 1px solid {settings['accent']}; }}
QWidget#SettingsPanel QPushButton:pressed {{
    background: {settings['hover']}; border-color: {settings['accent']};
}}
QWidget#SettingsPanel QPushButton:disabled {{
    color: {settings['muted']}; background: {settings['sidebar']};
    border-color: {settings['border']};
}}
QWidget#FloatingResultPanel QPushButton, QDialog#UpdateDialog QPushButton {{
    background: {colors['surface_alt']}; color: {colors['text']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QWidget#FloatingResultPanel QPushButton:hover,
QDialog#UpdateDialog QPushButton:hover {{
    background: {colors['surface_hover']}; border-color: {colors['accent']};
}}
QWidget#FloatingResultPanel QPushButton:focus,
QDialog#UpdateDialog QPushButton:focus {{ border: 2px solid {colors['accent']}; }}
QWidget#FloatingResultPanel QPushButton:pressed,
QDialog#UpdateDialog QPushButton:pressed {{
    background: {colors['surface_hover']}; border-color: {colors['accent']};
}}
QWidget#FloatingResultPanel QPushButton:disabled,
QDialog#UpdateDialog QPushButton:disabled {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-color: {colors['border']};
}}
QWidget#SettingsPanel QPushButton#NavButton {{
    background: transparent; border: none; color: {settings['muted']};
    border-radius: 9px; padding: 0 12px; text-align: left;
    font-weight: 500;
}}
QWidget#SettingsPanel QPushButton#NavButton:hover {{
    background: {settings['hover']}; color: {settings['text']};
}}
QWidget#SettingsPanel QPushButton#NavButton:checked {{
    background: {settings['accent_soft']}; color: {settings['accent']}; font-weight: 600;
}}
QLabel#NavMarker {{ background: transparent; border-radius: 2px; }}
QLabel#NavMarker[selected="true"] {{ background: {settings['accent']}; }}
QLabel#NavHint {{ color: {settings['muted']}; font-size: 11px; background: transparent; }}
QWidget#SettingsPanel QPushButton#GitHubLink {{
    background: transparent; color: {settings['muted']}; border: none;
    border-radius: 8px; padding: 0 8px; text-align: left;
    font-family: Consolas, monospace; font-size: 11px; font-weight: 500;
}}
QWidget#SettingsPanel QPushButton#GitHubLink:hover,
QWidget#SettingsPanel QPushButton#GitHubLink:focus {{
    background: {settings['hover']}; color: {settings['text']};
    border: 1px solid {settings['accent']};
}}
QWidget#SettingsPanel QPushButton#ThemeToggleButton {{
    background: transparent; color: {settings['muted']}; border: 1px solid {settings['border']};
    border-radius: 8px; padding: 0; font-size: 15px;
}}
QWidget#SettingsPanel QPushButton#ThemeToggleButton:hover {{
    background: {settings['hover']}; color: {settings['text']};
}}
QWidget#SettingsPanel QPushButton#SettingsPrimary {{
    background: {settings['accent']};
    border-color: {settings['accent']}; color: {settings['accent_text']};
}}
QWidget#SettingsPanel QPushButton#SettingsPrimary:hover {{
    background: {settings['accent_hover']}; border-color: {settings['accent_hover']};
}}
QWidget#SettingsPanel QPushButton#SettingsPrimary:pressed {{
    background: {settings['accent_hover']}; border-color: {settings['accent_hover']};
}}
QWidget#SettingsPanel QPushButton#SettingsPrimary:disabled {{
    color: {settings['muted']}; background: {settings['sidebar']};
    border-color: {settings['border']};
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary,
QPushButton#FloatingPrimary {{
    background: {colors['accent_primary']};
    border: 1px solid {colors['accent_primary']}; color: white;
    border-radius: 8px; padding: 8px 14px; font-weight: 600;
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:hover,
QPushButton#FloatingPrimary:hover {{
    background: {colors['accent_hover']}; border-color: {colors['accent_hover']};
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:pressed,
QPushButton#FloatingPrimary:pressed {{
    background: {colors['accent_pressed']}; border-color: {colors['accent_pressed']};
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:disabled {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-color: {colors['border']};
}}
QWidget#SettingsPanel QPushButton#ModeCard {{
    background: {settings['surface']}; border: 1px solid {settings['border']};
    border-radius: 12px; padding: 0; text-align: left; min-height: 84px;
}}
QWidget#SettingsPanel QPushButton#ModeCard:hover,
QWidget#SettingsPanel QPushButton#ModeCard:focus {{
    border: 1px solid {settings['accent']};
}}
QWidget#SettingsPanel QPushButton#ModeCard[selected="true"] {{
    background: {settings['accent_soft']}; border: 1px solid {settings['accent']};
}}
QWidget#SettingsPanel QPushButton#ModeCard:disabled {{
    background: {settings['sidebar']};
}}
QLabel#ModeIndicator {{
    border: 1px solid {settings['border']}; border-radius: 9px;
    color: {settings['accent']}; font-size: 10px;
}}
QLabel#ModeIndicator[selected="true"] {{ border-color: {settings['accent']}; }}
QLabel#ModeTitle {{ font-size: 15px; font-weight: 600; background: transparent; }}
QLabel#ModeTag {{
    color: {settings['accent']}; background: {settings['accent_soft']};
    border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 600;
}}
QLabel#ModeBody {{ color: {settings['muted']}; font-size: 13px; background: transparent; }}
QLabel#ModeMeta {{ color: {settings['muted']}; font-size: 11px; background: transparent; }}
QLabel#TriggerTag {{
    background: {settings['sidebar']}; border: 1px solid {settings['border']};
    border-radius: 7px; padding: 6px 10px; font-size: 12px;
}}
QWidget#SettingsPanel QPushButton#TutorialStepButton {{
    background: transparent; color: {settings['muted']};
    border: none; border-top: 3px solid {settings['border']};
    border-radius: 2px; padding: 6px 2px 0; text-align: left; font-size: 12px;
}}
QWidget#SettingsPanel QPushButton#TutorialStepButton[stepState="complete"],
QWidget#SettingsPanel QPushButton#TutorialStepButton[stepState="current"] {{
    border-top-color: {settings['accent']};
}}
QWidget#SettingsPanel QPushButton#TutorialStepButton[stepState="current"] {{
    color: {settings['accent']}; font-weight: 600;
}}
QWidget#SettingsPanel QPushButton#TutorialStepButton:hover {{
    color: {settings['text']};
}}
QLabel#TutorialHeading {{ font-size: 22px; font-weight: 600; }}
QLabel#TutorialBody {{ color: {settings['muted']}; font-size: 14px; }}
QLabel#TutorialTip {{
    color: {settings['muted']}; background: {settings['sidebar']};
    border: 1px solid {settings['border']}; border-radius: 9px;
    padding: 11px 13px; font-size: 12px;
}}
QWidget#TutorialIllustration {{
    background: {settings['sidebar']};
    border: 1px solid {settings['border']}; border-radius: 10px;
}}
QWidget#SettingsPanel QPushButton#SwatchButton {{
    padding: 0; border: 1px solid transparent; border-radius: 10px;
}}
QWidget#SettingsPanel QPushButton#SwatchButton:checked {{
    border: 3px solid {settings['text']};
}}
QWidget#SettingsPanel QPushButton#CustomColorButton {{
    background: transparent; color: {settings['muted']};
    border: 1px dashed {settings['border']}; border-radius: 10px; padding: 0;
}}
QWidget#SettingsPanel QPushButton#IconButton {{
    background: transparent; color: {settings['muted']}; border: none;
    border-radius: 6px; padding: 0; font-size: 20px;
}}
QWidget#SettingsPanel QPushButton#IconButton:hover {{
    background: {settings['hover']};
}}
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
QWidget#SettingsPanel QComboBox {{
    background: {settings['input']}; color: {settings['text']};
    border: 1px solid {settings['border']}; border-radius: 8px;
    padding: 8px 11px; min-width: 220px;
}}
QWidget#SettingsPanel QComboBox:hover,
QWidget#SettingsPanel QComboBox:focus {{ border-color: {settings['accent']}; }}
QWidget#SettingsPanel QComboBox QAbstractItemView {{
    background: {settings['surface']}; color: {settings['text']};
    border: 1px solid {settings['border']}; selection-background-color: {settings['accent']};
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QWidget#SettingsPanel QScrollArea {{ background: transparent; border: none; }}
QWidget#SettingsPanel QScrollArea > QWidget > QWidget {{ background: transparent; }}
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
QWidget#FloatingPreviewFrame QWidget#FloatingFormulaPreview,
QWidget#FloatingPreviewFrame QWidget#FloatingMathJaxPreview,
QWidget#FloatingPreviewFrame QLabel#FloatingMathJaxError {{
    background: transparent; border: none;
}}
QLabel#FloatingQuality {{ color: {colors['success']}; font-size: 12px; }}
QLabel#FloatingQuality[warning="true"] {{ color: {colors['warning']}; }}
QWidget#FloatingSourceSwitch {{
    background: {colors['surface_alt']}; border: 1px solid {colors['border']};
    border-radius: 8px;
}}
QPushButton#FloatingSourceButton {{
    background: transparent; color: {colors['muted']}; border: none;
    border-radius: 7px; padding: 6px 12px; min-height: 20px;
}}
QPushButton#FloatingSourceButton:hover {{
    background: {colors['surface_hover']}; color: {colors['text']};
}}
QPushButton#FloatingSourceButton:checked {{
    background: {colors['accent_soft']}; color: {colors['accent']};
}}
QPushButton#FloatingSourceButton:focus {{
    border: 2px solid {colors['accent']};
}}
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
        QPalette.ColorRole.Window,
        QColor("#f6f7f9" if normalized == "light" else "#0f1218"),
    )
    palette.setColor(
        QPalette.ColorRole.WindowText,
        QColor("#151a21" if normalized == "light" else "#e8ecf3"),
    )
    palette.setColor(
        QPalette.ColorRole.Base,
        QColor("#ffffff" if normalized == "light" else "#161a21"),
    )
    palette.setColor(
        QPalette.ColorRole.Text,
        QColor("#151a21" if normalized == "light" else "#e8ecf3"),
    )
    application.setPalette(palette)
    return normalized


APP_STYLESHEET = application_stylesheet("dark")
