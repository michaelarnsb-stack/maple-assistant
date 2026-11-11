"""Generate assets/icon.ico (orange circle with a white M). Run: python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse((8, 8, SIZE - 8, SIZE - 8), fill=(255, 140, 26, 255))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 150)
except OSError:
    font = ImageFont.load_default(size=150)
d.text((SIZE / 2, SIZE / 2 + 4), "M", font=font, fill="white", anchor="mm")
out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
