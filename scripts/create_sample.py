from pathlib import Path

from matplotlib import pyplot as plt


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "examples" / "sample_formula.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure = plt.figure(figsize=(7.2, 1.8), dpi=180, facecolor="white")
    figure.text(
        0.5,
        0.5,
        r"$\int_{0}^{\infty} e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}$",
        ha="center",
        va="center",
        fontsize=30,
        color="#111827",
    )
    plt.axis("off")
    figure.savefig(output, bbox_inches="tight", pad_inches=0.18, facecolor="white")
    plt.close(figure)
    print(output)


if __name__ == "__main__":
    main()
