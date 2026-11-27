"""Draws the Blendcam app icon (1024x1024, no alpha): an orange lens ring with a blue iris and an orbit path.

    python tools/make_icon.py
Writes ios/Blendcam/Assets.xcassets/AppIcon.appiconset/icon-1024.png. Needs Pillow.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 4  # supersampling
N = 1024 * S
ORANGE = (232, 125, 13)
ORANGE_LIGHT = (255, 170, 60)
BLUE = (38, 87, 135)
BLUE_LIGHT = (92, 160, 220)
BG_TOP = (44, 44, 48)
BG_BOTTOM = (20, 20, 23)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "ios", "Blendcam", "Assets.xcassets", "AppIcon.appiconset", "icon-1024.png")


def circle(d, cx, cy, r, **kw):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), **kw)


def main():
    img = Image.new("RGB", (N, N))
    px = img.load()
    for y in range(0, N, S):  # vertical gradient (coarse rows are enough before the downscale)
        t = y / N
        c = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for yy in range(y, min(N, y + S)):
            for x in range(N):
                px[x, yy] = c
    d = ImageDraw.Draw(img)
    cx, cy = N * 0.5, N * 0.52

    # orbit path behind the lens (tilted ellipse), drawn on its own layer
    orbit = Image.new("L", (N, N), 0)
    od = ImageDraw.Draw(orbit)
    w = int(N * 0.022)
    od.ellipse((N * 0.06, cy - N * 0.17, N * 0.94, cy + N * 0.17), outline=255, width=w)
    orbit = orbit.rotate(-18, resample=Image.BICUBIC, center=(cx, cy))
    img.paste(Image.new("RGB", (N, N), ORANGE_LIGHT), (0, 0), orbit)

    # lens: orange ring, dark gap, blue iris, pupil, highlight
    circle(d, cx, cy, N * 0.30, fill=ORANGE)
    circle(d, cx, cy, N * 0.235, fill=(24, 24, 28))
    circle(d, cx, cy, N * 0.19, fill=BLUE)
    circle(d, cx, cy, N * 0.13, fill=BLUE_LIGHT)
    circle(d, cx, cy, N * 0.075, fill=(12, 14, 20))
    circle(d, cx - N * 0.06, cy - N * 0.065, N * 0.032, fill=(255, 255, 255))

    # front part of the orbit over the lens + the "camera" dot riding on it
    front = Image.new("L", (N, N), 0)
    fd = ImageDraw.Draw(front)
    fd.arc((N * 0.06, cy - N * 0.17, N * 0.94, cy + N * 0.17), 20, 160, fill=255, width=w)
    front = front.rotate(-18, resample=Image.BICUBIC, center=(cx, cy))
    img.paste(Image.new("RGB", (N, N), ORANGE_LIGHT), (0, 0), front)
    a = math.radians(35)
    ex, ey = N * 0.44 * math.cos(a), N * 0.17 * math.sin(a)
    rot = math.radians(18)
    dx = ex * math.cos(rot) - ey * math.sin(rot)
    dy = ex * math.sin(rot) + ey * math.cos(rot)
    circle(d, cx + dx, cy + dy, N * 0.05, fill=(255, 255, 255))
    circle(d, cx + dx, cy + dy, N * 0.032, fill=ORANGE)

    img = img.filter(ImageFilter.GaussianBlur(S * 0.3)).resize((1024, 1024), Image.LANCZOS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, "PNG")
    print("saved", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
