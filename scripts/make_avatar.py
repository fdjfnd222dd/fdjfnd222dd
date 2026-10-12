#!/usr/bin/env python3
"""Draw docs/avatar.png (460x460) and docs/avatar-64.png: a Win95-style beige CRT icon.

Pixel art on a 57x57 grid. The 460 version is that grid scaled 8x (nearest) plus a
2px frame-grey border; the 64 version is the grid at 1:1 plus a 3-4px border, so the
pixels stay exact instead of being resampled. Palette is the Windows 95 system set
(grey #c0c0c0, navy #000080, teal #008080) plus two beiges for the monitor case.
Needs Pillow (pip install pillow in the venv).
"""
import os
from PIL import Image

N = 57
GREY, NAVY, TEAL, WHITE, BLACK, SHADE = "#c0c0c0", "#000080", "#008080", "#ffffff", "#000000", "#808080"
BEIGE, BEIGE_LT, BEIGE_DK = "#d8d0b8", "#f2eedc", "#8f8670"
GLINT, SCAN = "#5fc0c0", "#006868"

img = Image.new("RGB", (N, N), NAVY)
px = img.load()


def rect(x0, y0, x1, y1, c):
    """Inclusive cell rectangle."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px[x, y] = Image.new("RGB", (1, 1), c).getpixel((0, 0))


def bevel(x0, y0, x1, y1, tl, br, t=1):
    for i in range(t):
        rect(x0 + i, y0 + i, x1 - i, y0 + i, tl)      # top
        rect(x0 + i, y0 + i, x0 + i, y1 - i, tl)      # left
        rect(x0 + i, y1 - i, x1 - i, y1 - i, br)      # bottom
        rect(x1 - i, y0 + i, x1 - i, y1 - i, br)      # right


# window-frame ring: raised outside, sunken inside, navy "desktop" in the middle
rect(0, 0, N - 1, N - 1, GREY)
bevel(0, 0, N - 1, N - 1, WHITE, BLACK)
bevel(1, 1, N - 2, N - 2, GREY, SHADE)
rect(4, 4, N - 5, N - 5, NAVY)
bevel(3, 3, N - 4, N - 4, SHADE, WHITE)

# monitor case
mx0, my0, mx1, my1 = 12, 9, 44, 37
rect(mx0, my0, mx1, my1, BEIGE)
bevel(mx0, my0, mx1, my1, BEIGE_LT, BEIGE_DK, 2)
# bezel (sunken) and screen
rect(17, 14, 39, 31, BEIGE_DK)
bevel(17, 14, 39, 31, BLACK, BEIGE_LT)
rect(19, 16, 37, 29, TEAL)
rect(19, 16, 37, 16, SCAN)           # faint top scan edge
for y in (21, 25):                   # two scanlines
    rect(19, y, 37, y, SCAN)
rect(21, 18, 23, 18, GLINT)          # glint, top-left
rect(21, 19, 21, 20, GLINT)
# power led + vents on the chin
rect(40, 34, 41, 34, TEAL)
rect(16, 34, 16, 34, BEIGE_DK); rect(18, 34, 18, 34, BEIGE_DK); rect(20, 34, 20, 34, BEIGE_DK)
# neck and base
rect(22, 38, 34, 40, BEIGE)
bevel(22, 38, 34, 40, BEIGE_LT, BEIGE_DK, 1)
rect(15, 41, 41, 44, BEIGE)
bevel(15, 41, 41, 44, BEIGE_LT, BEIGE_DK, 1)
rect(16, 45, 42, 45, BLACK)          # hard drop shadow on the desktop

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
os.makedirs(out, exist_ok=True)
big = img.resize((N * 8, N * 8), Image.NEAREST)
canvas = Image.new("RGB", (460, 460), GREY)
canvas.paste(big, (2, 2))
canvas.save(os.path.join(out, "avatar.png"))
small = Image.new("RGB", (64, 64), GREY)
small.paste(img, (3, 3))
small.save(os.path.join(out, "avatar-64.png"))
print("wrote docs/avatar.png, docs/avatar-64.png")
