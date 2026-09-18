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
from formulasnip.ui.branding import TUTORIAL_FORMULA_LATEX  # noqa: E402
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
        TUTORIAL_FORMULA_LATEX,
        "MathCraft OCR（CPU）",
        0.71,
        "single",
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

        settings.show_recognition_page()
        app.processEvents()
        recognition_output = output_dir / "formulasnip_recognition_engine.png"
        save_widget(settings, recognition_output)

        settings.show_appearance_page()
        app.processEvents()
        appearance_output = output_dir / "formulasnip_appearance_live_preview.png"
        save_widget(settings, appearance_output)

        settings.show_tutorial()
        app.processEvents()
        tutorial_output = output_dir / "formulasnip_quick_start.png"
        save_widget(settings, tutorial_output)

        tutorial_images: list[QPixmap] = []
        for step_index, illustration in enumerate(settings.tutorial_illustrations):
            settings._set_tutorial_step(step_index)
            app.processEvents()
            tutorial_images.append(illustration.grab())
        illustration_width = max(image.width() for image in tutorial_images)
        illustration_height = max(image.height() for image in tutorial_images)
        illustration_gap = 20
        illustration_margin = 20
        tutorial_canvas = QPixmap(
            illustration_margin * 2 + illustration_width * 2 + illustration_gap,
            illustration_margin * 2 + illustration_height * 2 + illustration_gap,
        )
        tutorial_canvas.fill(QColor("#eef3f9"))
        tutorial_painter = QPainter(tutorial_canvas)
        for step_index, image in enumerate(tutorial_images):
            column = step_index % 2
            row = step_index // 2
            x = illustration_margin + column * (illustration_width + illustration_gap)
            y = illustration_margin + row * (illustration_height + illustration_gap)
            tutorial_painter.drawPixmap(x, y, image)
        tutorial_painter.end()
        tutorial_illustrations_output = (
            output_dir / "formulasnip_tutorial_illustrations.png"
        )
        if not tutorial_canvas.save(str(tutorial_illustrations_output), "PNG"):
            raise RuntimeError(
                f"无法保存教程图示预览：{tutorial_illustrations_output}"
            )

        settings.hide()

    panel.close()
    orb.close()
    for output in (
        floating_output,
        dark_settings_output,
        light_settings_output,
        recognition_output,
        appearance_output,
        tutorial_output,
        tutorial_illustrations_output,
    ):
        print(output)


if __name__ == "__main__":
    main()
