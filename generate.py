import json
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

TEXT = "Me: I'll go to bed early tonight\nMe at 3 AM: watching raccoon videos"
CAPTION = "We've all been here 😅 #relatable #memes #scrollstroll"

img = Image.new("RGB", (1080, 1080), "#111111")
draw = ImageDraw.Draw(img)
font = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64
)

y = 250
for line in TEXT.split("\n"):
    for wrapped in textwrap.wrap(line, width=24):
        draw.text((80, y), wrapped, font=font, fill="white")
        y += 90
    y += 80

os.makedirs("output", exist_ok=True)
img.save("output/today.jpg", "JPEG", quality=95)

with open("output/today.json", "w") as f:
    json.dump({"caption": CAPTION, "image": "today.jpg"}, f)

print("Meme created!")
