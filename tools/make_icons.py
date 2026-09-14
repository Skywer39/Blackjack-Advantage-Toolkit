"""Generate the app icons.

The mark is the bet ramp itself -- five bars stepping up to the right, the shape
the whole tool exists to produce. Drawn full bleed because iOS masks the icon to
its own rounded rectangle, and a pre-rounded source would be clipped twice.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

GROUND = (18, 22, 19)      # --ground, dark
ACCENT = (63, 174, 122)    # --accent, chip green
DIM = (43, 51, 46)         # --line, for the counts you sit out

#: Bar heights as a fraction of the drawable area, low counts to high.
STEPS = (0.20, 0.20, 0.38, 0.58, 0.80, 1.00)
#: The first two are table-minimum bets: drawn dim, because the ramp's whole
#: point is that most of it is waiting.
DIM_STEPS = 2

SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
}


def draw(size: int) -> Image.Image:
    # Supersample, then downscale: crisp edges at 32px without hinting games.
    scale = 4
    s = size * scale
    img = Image.new("RGB", (s, s), GROUND)
    d = ImageDraw.Draw(img)

    pad = s * 0.17
    inner = s - 2 * pad
    n = len(STEPS)
    gap = inner * 0.055
    bar_w = (inner - gap * (n - 1)) / n
    radius = max(1, int(bar_w * 0.22))

    for i, frac in enumerate(STEPS):
        h = inner * frac
        x0 = pad + i * (bar_w + gap)
        y1 = pad + inner
        d.rounded_rectangle(
            [x0, y1 - h, x0 + bar_w, y1],
            radius=radius,
            fill=DIM if i < DIM_STEPS else ACCENT,
        )
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "web" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for name, size in SIZES.items():
        draw(size).save(out / name, optimize=True)
        print(f"wrote {out / name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
