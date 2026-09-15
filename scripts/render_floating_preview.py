from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QRect, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402

from formulasnip.app import create_application  # noqa: E402
from formulasnip.domain import RecognitionResult  # noqa: E402
from formulasnip.ui.floating import FloatingOrb, FloatingResultPanel  # noqa: E402
from formulasnip.ui.settings import FloatingPreferences, SettingsPanel  # noqa: E402
from formulasnip.ui.styles import apply_application_theme  # noqa: E402


def save_widget(widget: object, output: Path) -> None:
    pixmap = widget.grab()  # type: ignore[attr-defined]
    if not pixmap.save(str(output), "PNG"):
        raise RuntimeError(f"无法保存界面预览：{output}")


def main() -> None:
    output_dir = PROJECT_ROOT / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)

    app = create_application([])
    apply_application_theme("dark")
    orb = FloatingOrb("#28A9C7")
    panel = FloatingResultPanel()
    result = RecognitionResult(
        r"\int_{0}^{\infty}e^{-x^{2}}\,d x=\frac{\sqrt{\pi}}{2}",
        "PP-FormulaNet-S（CPU）",
        0.71,
        "auto-reviewed",
    )
    orb.set_result_available(True)
    orb.show()
    panel.show_result(result, QRect(900, 180, 68, 68))
    app.processEvents()

    panel_image = panel.grab()
    orb_image = orb.grab()
    canvas = QPixmap(760, 520)
    canvas.fill(QColor("#eef3f9"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(QRect(24, 22, 712, 476), 12, 12)
    painter.drawPixmap(48, 48, panel_image)
    painter.drawPixmap(628, 205, orb_image)
    painter.end()

    floating_output = output_dir / "formulasnip_floating_result_dark.png"
    if not canvas.save(str(floating_output), "PNG"):
        raise RuntimeError(f"无法保存悬浮模式预览：{floating_output}")

    with tempfile.TemporaryDirectory(prefix="formulasnip-preview-") as temporary:
        settings_store = QSettings(
            str(Path(temporary) / "preview.ini"), QSettings.Format.IniFormat
        )
        settings = SettingsPanel(settings_store, FloatingPreferences())
        settings.show()
        app.processEvents()
        dark_settings_output = output_dir / "formulasnip_settings_center_dark.png"
        save_widget(settings, dark_settings_output)

        settings.theme_toggle_button.click()
        app.processEvents()
        light_settings_output = output_dir / "formulasnip_settings_center_light.png"
        save_widget(settings, light_settings_output)

        settings.show_appearance_page()
        app.processEvents()
        appearance_output = output_dir / "formulasnip_appearance_live_preview.png"
        save_widget(settings, appearance_output)

        settings.show_tutorial()
        app.processEvents()
        tutorial_output = output_dir / "formulasnip_quick_start.png"
        save_widget(settings, tutorial_output)

        settings.hide()

    panel.close()
    orb.close()
    for output in (
        floating_output,
        dark_settings_output,
        light_settings_output,
        appearance_output,
        tutorial_output,
    ):
        print(output)


if __name__ == "__main__":
    main()
