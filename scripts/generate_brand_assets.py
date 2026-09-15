from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from formulasnip.ui.branding import TUTORIAL_FORMULA_LATEX

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PROJECT_ROOT / "formulasnip" / "assets"
ICON_SIZE = 512


def _brand_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/seguisb.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def generate_icon() -> None:
    canvas = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    margin = 28
    draw.rounded_rectangle(
        (margin, margin, ICON_SIZE - margin, ICON_SIZE - margin),
        radius=112,
        fill="#315FDD",
    )
    draw.rounded_rectangle(
        (margin + 12, margin + 12, ICON_SIZE - margin - 12, ICON_SIZE - margin - 12),
        radius=101,
        outline="#5D83F3",
        width=9,
    )
    font = _brand_font(198)
    text = "fx"
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    position = (
        (ICON_SIZE - width) / 2 - bounds[0],
        (ICON_SIZE - height) / 2 - bounds[1] - 9,
    )
    draw.text(position, text, font=font, fill="#FFFFFF")
    canvas.save(ASSET_DIR / "formulasnip.png", "PNG")
    canvas.save(
        ASSET_DIR / "formulasnip.ico",
        "ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)],
    )


def generate_formula() -> None:
    from matplotlib.mathtext import math_to_image

    math_to_image(
        f"${TUTORIAL_FORMULA_LATEX}$",
        ASSET_DIR / "tutorial_gaussian_integral.png",
        dpi=300,
        format="png",
        color="#172033",
    )


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    generate_icon()
    generate_formula()
    for path in (
        ASSET_DIR / "formulasnip.png",
        ASSET_DIR / "formulasnip.ico",
        ASSET_DIR / "tutorial_gaussian_integral.png",
    ):
        print(path)


if __name__ == "__main__":
    main()
