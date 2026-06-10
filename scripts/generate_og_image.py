"""
scripts/generate_og_image.py
Genera web/og-default.png (1200x630) para previews sociales (WhatsApp, X, FB,
Telegram). Replica el diseno de web/og-default.svg con Pillow.

Por que un PNG y no el SVG: WhatsApp/Facebook/X NO renderizan SVG en og:image.
El SVG lo dejamos como version vectorial para otros usos (por ejemplo, mostrar
el logo en HTML con calidad infinita).

Correr cuando se cambie el diseno:
    python scripts/generate_og_image.py
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "web" / "og-default.png"

W, H = 1200, 630
BG       = (10, 14, 19)       # #0a0e13
LINE     = (26, 42, 26)       # #1a2a1a campo de futbol sutil
GREEN    = (34, 197, 94)      # #22c55e FutVS green
WHITE    = (255, 255, 255)
GRAY     = (107, 114, 128)    # #6b7280 tagline
GRAY_DK  = (55, 65, 81)       # #374151 URL
CHIP_BG  = (15, 42, 26)       # #0f2a1a
CHIP_BORDER = (34, 197, 94, 100)  # green con alpha


def _font(*names, size: int) -> ImageFont.FreeTypeFont:
    """Carga la primera font disponible de la lista."""
    win_fonts = "C:/Windows/Fonts/"
    for name in names:
        for path in (name, win_fonts + name):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # ─── Lineas de campo de futbol (muy sutiles) ───────────────────────────
    d.rectangle([80, 60, 1120, 570], outline=LINE, width=2)
    d.line([(600, 60), (600, 570)], fill=LINE, width=2)
    d.ellipse([510, 225, 690, 405], outline=LINE, width=2)
    d.ellipse([595, 310, 605, 320], fill=LINE)
    d.rectangle([80, 210, 210, 420], outline=LINE, width=2)
    d.rectangle([990, 210, 1120, 420], outline=LINE, width=2)

    # ─── Glow verde central sutil ──────────────────────────────────────────
    # Pillow no tiene radial gradient nativo; simulamos con varios circulos
    # concentricos translucidos.
    for r, alpha in [(450, 6), (350, 10), (250, 14), (150, 18)]:
        d.ellipse([600-r, 315-r, 600+r, 315+r], fill=(34, 197, 94, alpha))

    # ─── Logo FUTVS ────────────────────────────────────────────────────────
    font_logo = _font("ariblk.ttf", "arial.ttf", size=170)
    # Medir cada parte para centrar
    fut_text = "FUT"
    vs_text  = "VS"
    fut_w = d.textlength(fut_text, font=font_logo)
    vs_w  = d.textlength(vs_text,  font=font_logo)
    total_w = fut_w + vs_w
    x_start = (W - total_w) // 2
    y_logo = 130
    d.text((x_start, y_logo), fut_text, font=font_logo, fill=WHITE)
    d.text((x_start + fut_w, y_logo), vs_text, font=font_logo, fill=GREEN)

    # ─── Linea verde separadora ────────────────────────────────────────────
    d.rectangle([420, 358, 780, 362], fill=(34, 197, 94, 160))

    # ─── Tagline ───────────────────────────────────────────────────────────
    font_tag = _font("arial.ttf", size=22)
    tagline = "PRONOSTICOS  CON  INTELIGENCIA  ESTADISTICA"
    tag_w = d.textlength(tagline, font=font_tag)
    d.text(((W - tag_w) // 2, 388), tagline, font=font_tag, fill=GRAY)

    # ─── Chips de tecnologia ───────────────────────────────────────────────
    chips = ["DIXON-COLES", "ELO", "XGBOOST", "ISOTONIC"]
    font_chip = _font("consola.ttf", "cour.ttf", "arial.ttf", size=14)
    gap = 16
    pad_x = 22
    chip_h = 36
    # Calcular ancho de cada chip + total para centrar
    chip_widths = [int(d.textlength(c, font=font_chip)) + pad_x * 2 for c in chips]
    total_chips_w = sum(chip_widths) + gap * (len(chips) - 1)
    x = (W - total_chips_w) // 2
    y_chip = 455
    for c, cw in zip(chips, chip_widths):
        d.rounded_rectangle(
            [x, y_chip, x + cw, y_chip + chip_h],
            radius=18, fill=CHIP_BG, outline=CHIP_BORDER, width=1,
        )
        tw = d.textlength(c, font=font_chip)
        d.text((x + (cw - tw) // 2, y_chip + 10), c, font=font_chip, fill=GREEN)
        x += cw + gap

    # ─── URL ───────────────────────────────────────────────────────────────
    font_url = _font("consola.ttf", "cour.ttf", "arial.ttf", size=16)
    url = "futversus.com"
    url_w = d.textlength(url, font=font_url)
    d.text(((W - url_w) // 2, 560), url, font=font_url, fill=GRAY_DK)

    img.save(OUT_PATH, "PNG", optimize=True)
    print(f"[og] -> {OUT_PATH} ({OUT_PATH.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
