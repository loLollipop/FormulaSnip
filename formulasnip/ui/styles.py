from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DEFAULT_ACCENT_THEME = "blue"
ACCENT_THEME_SWATCHES = {
    "blue": "#3B82F6",
    "violet": "#7C6CF7",
    "cyan": "#0E93AD",
    "teal": "#15967F",
}
_ACCENT_THEME_PALETTES = {
    "blue": {
        "light": {
            "accent": "#2563EB",
            "primary": "#2563EB",
            "hover": "#1D4ED8",
            "pressed": "#1E40AF",
            "soft": "#EAF2FF",
            "text": "#FFFFFF",
        },
        "dark": {
            "accent": "#7DB2FF",
            "primary": "#3B82F6",
            "hover": "#5695F7",
            "pressed": "#2F6ED3",
            "soft": "#14233D",
            "text": "#08111F",
        },
    },
    "violet": {
        "light": {
            "accent": "#6D5DFB",
            "primary": "#6655E8",
            "hover": "#5848D6",
            "pressed": "#493ABF",
            "soft": "#EEEBFF",
            "text": "#FFFFFF",
        },
        "dark": {
            "accent": "#A99BFF",
            "primary": "#7665F5",
            "hover": "#8879FF",
            "pressed": "#6554DD",
            "soft": "#24203A",
            "text": "#10111A",
        },
    },
    "cyan": {
        "light": {
            "accent": "#087F9C",
            "primary": "#087F9C",
            "hover": "#066D88",
            "pressed": "#055A70",
            "soft": "#E5F7FA",
            "text": "#FFFFFF",
        },
        "dark": {
            "accent": "#52C7DB",
            "primary": "#0E7D95",
            "hover": "#168CA4",
            "pressed": "#0A687C",
            "soft": "#102A32",
            "text": "#071316",
        },
    },
    "teal": {
        "light": {
            "accent": "#0F7F6F",
            "primary": "#0F7F6F",
            "hover": "#0B6D60",
            "pressed": "#09594F",
            "soft": "#E8F7F3",
            "text": "#FFFFFF",
        },
        "dark": {
            "accent": "#58CFB7",
            "primary": "#0F766E",
            "hover": "#168A75",
            "pressed": "#0B625B",
            "soft": "#102C27",
            "text": "#071512",
        },
    },
}


def normalize_accent_theme(accent_theme: object) -> str:
    normalized = str(accent_theme).strip().lower()
    return (
        normalized
        if normalized in _ACCENT_THEME_PALETTES
        else DEFAULT_ACCENT_THEME
    )


def theme_accent_color(theme: str, accent_theme: object = DEFAULT_ACCENT_THEME) -> str:
    scheme = "light" if theme == "light" else "dark"
    accent = normalize_accent_theme(accent_theme)
    return _ACCENT_THEME_PALETTES[accent][scheme]["accent"]


def current_accent_color() -> str:
    application = QApplication.instance()
    if application is None:
        return theme_accent_color("dark")
    return theme_accent_color(
        str(application.property("theme") or "dark"),
        application.property("accentTheme"),
    )


def application_stylesheet(
    theme: str,
    accent_theme: object = DEFAULT_ACCENT_THEME,
) -> str:
    """Return the complete application stylesheet for the selected theme."""
    light = theme == "light"
    scheme = "light" if light else "dark"
    accent_name = normalize_accent_theme(accent_theme)
    accent = _ACCENT_THEME_PALETTES[accent_name][scheme]
    colors = {
        "window": "#f6f7fb" if light else "#0b0d12",
        "surface": "#ffffff" if light else "#131620",
        "surface_alt": "#f1f3f9" if light else "#191d29",
        "surface_hover": "#e9ecf5" if light else "#222838",
        "sidebar": "#eef1f8" if light else "#090b10",
        "text": "#171923" if light else "#f1f3f8",
        "muted": "#64697a" if light else "#9aa3b5",
        "border": "#dee2ec" if light else "#252b3a",
        "border_strong": "#c7cedd" if light else "#3a4255",
        "accent": accent["accent"],
        "accent_primary": accent["primary"],
        "accent_hover": accent["hover"],
        "accent_pressed": accent["pressed"],
        "accent_soft": accent["soft"],
        "accent_text": accent["text"],
        "code": "#f3f4f8" if light else "#0e1118",
        "success": "#0f8a78" if light else "#2dd4bf",
        "success_soft": "#e8f8f5" if light else "#102d2a",
        "warning": "#a35a00" if light else "#f4b942",
        "warning_soft": "#fff6e6" if light else "#35280e",
        "error": "#b42318" if light else "#fda29b",
        "error_soft": "#fff1f0" if light else "#321b20",
    }
    settings = {
        "window": "#F6F7FB" if light else "#0C0E14",
        "surface": "#FFFFFF" if light else "#141822",
        "sidebar": "#F9FAFD" if light else "#090B10",
        "border": "#DDE2EE" if light else "#2A3040",
        "text": "#1B1D28" if light else "#F3F5FA",
        "muted": "#697083" if light else "#9BA5B8",
        "accent": accent["accent"],
        "accent_soft": accent["soft"],
        "accent_hover": accent["hover"],
        "accent_text": accent["text"],
        "hover": "#EEF1F7" if light else "#1C2230",
        "input": "#FFFFFF" if light else "#10131B",
        "warning": "#A35A00" if light else "#F4B942",
        "warning_soft": "#FFF6E6" if light else "#35280E",
    }
    return f"""
QWidget {{
    color: {colors['text']};
    font-size: 14px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
}}
QWidget#SettingsPanel, QWidget#SettingsPanel QWidget {{
    color: {settings['text']};
    font-size: 15px;
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
QScrollArea#UpdateContentScroll QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 4px 2px 4px 0;
}}
QTextBrowser#UpdateNotes QScrollBar::handle:vertical,
QScrollArea#UpdateContentScroll QScrollBar::handle:vertical {{
    background: {colors['border_strong']}; min-height: 28px; border-radius: 4px;
}}
QTextBrowser#UpdateNotes QScrollBar::handle:vertical:hover,
QScrollArea#UpdateContentScroll QScrollBar::handle:vertical:hover {{
    background: {colors['muted']};
}}
QTextBrowser#UpdateNotes QScrollBar::add-line:vertical,
QTextBrowser#UpdateNotes QScrollBar::sub-line:vertical,
QScrollArea#UpdateContentScroll QScrollBar::add-line:vertical,
QScrollArea#UpdateContentScroll QScrollBar::sub-line:vertical {{ height: 0; }}
QTextBrowser#UpdateNotes QScrollBar::add-page:vertical,
QTextBrowser#UpdateNotes QScrollBar::sub-page:vertical,
QScrollArea#UpdateContentScroll QScrollBar::add-page:vertical,
QScrollArea#UpdateContentScroll QScrollBar::sub-page:vertical {{ background: transparent; }}
QLabel#UpdateMetaChip {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border: 1px solid {colors['border']}; border-radius: 7px;
    padding: 4px 9px; font-size: 12px;
}}
QFrame#UpdateStatusPanel {{
    background: {colors['accent_soft']}; border: 1px solid {colors['border']};
    border-radius: 9px;
}}
QFrame#UpdateStatusPanel[state="error"] {{
    background: {colors['error_soft']}; border-color: {colors['error']};
}}
QLabel#UpdateStatusLabel {{ background: transparent; font-size: 13px; }}
QFrame#UpdateStatusPanel[state="error"] QLabel#UpdateStatusLabel {{
    color: {colors['error']};
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
QLabel#BrandEdition, QLabel#SettingsHint,
QLabel#CardDescription, QLabel#TutorialCounter, QLabel#MutedText,
QLabel#LogoSafetyText {{ color: {settings['muted']}; }}
QLabel#BrandEdition {{ font-size: 12px; }}
QLabel#PageTitle {{ font-size: 21px; font-weight: 600; }}
QLabel#SettingsHint, QLabel#CardDescription, QLabel#TutorialCounter,
QLabel#MutedText, QLabel#LogoSafetyText {{ font-size: 13px; }}
QLabel#SettingsErrorBanner {{
    color: {settings['warning']}; background: {settings['warning_soft']};
    border: 1px solid {settings['warning']}; border-radius: 8px;
    margin: 10px 28px 0 28px; padding: 9px 12px;
}}
QLabel#CardTitle, QLabel#SettingsFieldLabel, QLabel#RowTitle {{
    font-size: 15px; font-weight: 600;
}}
QLabel#OfflineCard {{
    background: {settings['surface']}; color: {settings['muted']};
    border: 1px solid {settings['border']}; border-radius: 8px;
    padding: 12px; font-size: 13px;
}}
QWidget#SettingsCard, QWidget#OverviewModeCard, QWidget#RecognitionTriggerCard,
QStackedWidget#TutorialStack {{
    background: {settings['surface']};
    border: 1px solid {settings['border']};
    border-radius: 10px;
}}
QFrame#CardDivider {{
    border: none; border-top: 1px solid {settings['border']};
    max-height: 1px;
}}
QWidget#SettingsCTA {{
    background: {settings['accent_soft']};
    border: 1px solid {settings['border']};
    border-radius: 10px;
}}
QWidget#OrbPreviewStage {{
    background: {settings['sidebar']};
    border: 1px solid {settings['border']};
    border-radius: 10px;
}}
QLabel#RingHexLabel {{
    color: {settings['muted']}; background: transparent;
    font-family: Consolas, monospace; font-size: 12px;
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
    padding: 4px 0; font-size: 13px;
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
QLabel#ApiKeyStatus {{ color: {settings['muted']}; font-size: 13px; }}
QLabel#ApiKeyStatus[saved="true"] {{ color: {colors['success']}; }}
QLabel#ApiKeyStatus[error="true"] {{ color: {colors['warning']}; }}
QLabel#AiConnectionStatus {{ color: {settings['muted']}; font-size: 13px; }}
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
QWidget#SettingsPanel QPushButton:focus {{ border: 2px solid {settings['accent']}; }}
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
QWidget#FloatingResultPanel QPushButton#FloatingCloseButton {{
    background: transparent; color: {colors['muted']};
    border: 1px solid transparent; border-radius: 8px;
    padding: 0; font-size: 21px; font-weight: 400;
}}
QWidget#FloatingResultPanel QPushButton#FloatingCloseButton:hover,
QWidget#FloatingResultPanel QPushButton#FloatingCloseButton:focus {{
    background: {colors['surface_hover']}; border-color: {colors['accent']};
}}
QWidget#SettingsPanel QPushButton#NavButton {{
    background: transparent; border: 1px solid transparent; color: {settings['muted']};
    border-radius: 8px; padding: 0 12px; text-align: left;
    font-weight: 500;
}}
QWidget#SettingsPanel QPushButton#NavButton:hover {{
    background: {settings['hover']}; color: {settings['text']};
}}
QWidget#SettingsPanel QPushButton#NavButton:checked {{
    background: {settings['accent_soft']}; color: {settings['accent']};
    border-color: {settings['border']}; font-weight: 600;
}}
QLabel#NavMarker {{ background: transparent; border-radius: 2px; }}
QLabel#NavMarker[selected="true"] {{ background: {settings['accent']}; }}
QLabel#NavHint {{ color: {settings['muted']}; font-size: 13px; background: transparent; }}
QWidget#SettingsPanel QPushButton#GitHubLink {{
    background: transparent; color: {settings['muted']}; border: none;
    border-radius: 8px; padding: 0 8px; text-align: left;
    font-family: Consolas, monospace; font-size: 12px; font-weight: 500;
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
QWidget#FloatingResultPanel QPushButton#FloatingPrimary {{
    background: {colors['accent_primary']};
    border: 1px solid {colors['accent_primary']}; color: white;
    border-radius: 8px; padding: 8px 14px; font-weight: 600;
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:hover,
QWidget#FloatingResultPanel QPushButton#FloatingPrimary:hover {{
    background: {colors['accent_hover']}; border-color: {colors['accent_hover']};
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:pressed,
QWidget#FloatingResultPanel QPushButton#FloatingPrimary:pressed {{
    background: {colors['accent_pressed']}; border-color: {colors['accent_pressed']};
}}
QDialog#UpdateDialog QPushButton#SettingsPrimary:disabled {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-color: {colors['border']};
}}
QWidget#FloatingResultPanel QPushButton#FloatingPrimary:disabled {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border-color: {colors['border']};
}}
QWidget#SettingsPanel QPushButton#ModeCard {{
    background: {settings['surface']}; border: 1px solid {settings['border']};
    border-radius: 10px; padding: 0; text-align: left; min-height: 68px;
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
    border-radius: 8px; padding: 2px 8px; font-size: 12px; font-weight: 600;
}}
QLabel#TriggerTag {{
    background: {settings['sidebar']}; border: 1px solid {settings['border']};
    border-radius: 7px; padding: 6px 10px; font-size: 13px;
}}
QWidget#SettingsPanel QPushButton#TutorialStepButton {{
    background: transparent; color: {settings['muted']};
    border: none; border-top: 3px solid {settings['border']};
    border-radius: 2px; padding: 6px 2px 0; text-align: left; font-size: 13px;
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
QLabel#TutorialBody {{ color: {settings['muted']}; font-size: 15px; }}
QWidget#TutorialIllustration {{
    background: {settings['sidebar']};
    border: 1px solid {settings['border']}; border-radius: 10px;
}}
QWidget#SettingsPanel QPushButton#SwatchButton,
QWidget#SettingsPanel QPushButton#ThemeSwatchButton {{
    padding: 0; border: 1px solid transparent; border-radius: 10px;
}}
QWidget#SettingsPanel QPushButton#SwatchButton:checked,
QWidget#SettingsPanel QPushButton#ThemeSwatchButton:checked {{
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
    border: 1px solid {colors['border_strong']}; border-radius: 14px;
}}
QWidget#FloatingResultHeader {{
    background: transparent; border: none;
    border-bottom: 1px solid {colors['border']};
}}
QLabel#FloatingBrandBadge {{
    background: {colors['accent_soft']}; border: 1px solid {colors['border']};
    border-radius: 9px;
}}
QLabel#FloatingResultTitle {{ color: {colors['text']}; font-size: 18px; font-weight: 700; }}
QLabel#FloatingMeta {{
    color: {colors['accent']}; background: {colors['accent_soft']};
    border: 1px solid {colors['border']}; border-radius: 8px;
    padding: 5px 9px; font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 11px;
}}
QStackedWidget#FloatingPreviewStack, QWidget#FloatingPreviewFrame,
QLabel#FloatingPreviewMessage {{
    background: #ffffff; color: #263247; border: 1px solid #d5dceb;
    border-radius: 10px;
}}
QStackedWidget#FloatingPreviewStack:focus {{
    border: 2px solid {colors['accent']};
}}
QWidget#FloatingPreviewFrame QWidget#FloatingFormulaPreview,
QWidget#FloatingPreviewFrame QWidget#FloatingMathJaxPreview,
QWidget#FloatingPreviewFrame QLabel#FloatingMathJaxError {{
    background: transparent; border: none;
}}
QLabel#FloatingQuality {{
    color: {colors['success']}; background: {colors['success_soft']};
    border: 1px solid {colors['success']}; border-radius: 8px;
    padding: 7px 10px; font-size: 12px;
}}
QLabel#FloatingQuality[warning="true"] {{
    color: {colors['warning']}; background: {colors['warning_soft']};
    border-color: {colors['warning']};
}}
QWidget#FloatingSourceSwitch {{
    background: {colors['code']}; border: 1px solid {colors['border']};
    border-radius: 9px;
}}
QWidget#FloatingResultPanel QPushButton#FloatingSourceButton {{
    background: transparent; color: {colors['muted']}; border: none;
    border-radius: 7px; padding: 6px 12px; min-height: 20px;
}}
QWidget#FloatingResultPanel QPushButton#FloatingSourceButton:hover {{
    background: {colors['surface_hover']}; color: {colors['text']};
}}
QWidget#FloatingResultPanel QPushButton#FloatingSourceButton:checked {{
    background: {colors['accent_soft']}; color: {colors['accent']};
}}
QWidget#FloatingResultPanel QPushButton#FloatingSourceButton:focus {{
    border: 2px solid {colors['accent']};
}}
QPlainTextEdit#FloatingLatex {{
    background: {colors['code']}; color: {colors['text']};
    border: 1px solid {colors['border_strong']}; border-radius: 9px;
    padding: 9px 11px; font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 12px; selection-background-color: {colors['accent_primary']};
}}
QPlainTextEdit#FloatingLatex:focus {{ border: 2px solid {colors['accent']}; }}
QPlainTextEdit#FloatingLatex QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 4px 2px 4px 0;
}}
QPlainTextEdit#FloatingLatex QScrollBar::handle:vertical {{
    background: {colors['border_strong']}; min-height: 24px; border-radius: 4px;
}}
QPlainTextEdit#FloatingLatex QScrollBar::add-line:vertical,
QPlainTextEdit#FloatingLatex QScrollBar::sub-line:vertical {{ height: 0; }}
QWidget#FloatingResultPanel QPushButton#FloatingRecapture {{
    background: transparent; color: {colors['muted']};
    border: 1px solid {colors['border']};
}}
QWidget#FloatingResultPanel QPushButton#FloatingRecapture:hover,
QWidget#FloatingResultPanel QPushButton#FloatingRecapture:focus {{
    color: {colors['text']}; background: {colors['surface_alt']};
    border-color: {colors['accent']};
}}
QLabel#FloatingStatus {{
    color: {colors['muted']}; background: {colors['surface_alt']};
    border: 1px solid {colors['border']}; border-radius: 7px;
    padding: 6px 8px; font-size: 12px;
}}
QLabel#FloatingStatus[state="success"] {{
    color: {colors['success']}; background: {colors['success_soft']};
    border-color: {colors['success']};
}}
QLabel#FloatingStatus[state="error"] {{
    color: {colors['error']}; background: {colors['error_soft']};
    border: 1px solid {colors['error']}; border-radius: 7px; padding: 6px 8px;
}}
QMenu {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; padding: 6px;
}}
QMenu::item {{ padding: 9px 24px 9px 10px; border-radius: 5px; }}
QMenu::item:selected {{
    background: {colors['accent']}; color: {colors['accent_text']};
}}
QToolTip {{
    background: {colors['surface']}; color: {colors['text']};
    border: 1px solid {colors['border']}; padding: 5px;
}}
"""


def apply_application_theme(
    theme: str,
    accent_theme: object = DEFAULT_ACCENT_THEME,
) -> str:
    """Apply theme to every application-owned surface, including menus."""
    normalized = "light" if theme == "light" else "dark"
    normalized_accent = normalize_accent_theme(accent_theme)
    application = QApplication.instance()
    if application is None:
        return normalized
    application.setProperty("theme", normalized)
    application.setProperty("accentTheme", normalized_accent)
    application.setStyleSheet(
        application_stylesheet(normalized, normalized_accent)
    )
    palette = QPalette()
    palette.setColor(
        QPalette.ColorRole.Window,
        QColor("#f6f7fb" if normalized == "light" else "#0b0d12"),
    )
    palette.setColor(
        QPalette.ColorRole.WindowText,
        QColor("#171923" if normalized == "light" else "#f1f3f8"),
    )
    palette.setColor(
        QPalette.ColorRole.Base,
        QColor("#ffffff" if normalized == "light" else "#131620"),
    )
    palette.setColor(
        QPalette.ColorRole.Text,
        QColor("#171923" if normalized == "light" else "#f1f3f8"),
    )
    palette.setColor(
        QPalette.ColorRole.Highlight,
        QColor(theme_accent_color(normalized, normalized_accent)),
    )
    palette.setColor(
        QPalette.ColorRole.HighlightedText,
        QColor("#ffffff" if normalized == "light" else "#08111f"),
    )
    application.setPalette(palette)
    return normalized


APP_STYLESHEET = application_stylesheet("dark")
