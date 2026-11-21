"""TheScrollStroll - Reel lane.

Creates a vertical (1080x1920) quote Reel: looping background video + auto-fitted text.
Outputs reels/out/reel.mp4 and reels/out/reel.json (caption + video url for Make).

Secrets (all optional - the script still works with none of them):
  PIXABAY_API_KEY  -> real video backgrounds (otherwise an animated gradient is used)
  GEMINI_API_KEY   -> fresh AI-written quotes (otherwise the built-in list is used)
"""
import json
import os
import random
import subprocess
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
OUT_DIR = Path("reels/out")
TMP_DIR = Path("reels/tmp")
HANDLE = "@TheScrollStroll"
REPO_RAW = os.environ.get(
    "REPO_RAW_BASE",
    "https://raw.githubusercontent.com/aakarshmodiuk-hub/thescrollstroll-bot/main",
)

# Text must stay inside this safe box (Instagram's UI covers the very top/bottom/right edge)
BOX_LEFT, BOX_RIGHT = 90, W - 90
BOX_TOP, BOX_BOTTOM = 420, 1380
MAX_FONT, MIN_FONT = 112, 52

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/montserrat/Montserrat[wght].ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# category -> (background search terms, hashtags)
CATEGORIES = {
    "inspiration": (["sunrise", "mountain clouds", "ocean waves", "forest light"],
                    "#motivation #inspiration #mindset #growth"),
    "professional life": (["city skyline", "office window", "city night", "laptop work"],
                          "#careergrowth #worklife #leadership #success"),
    "personal life": (["rain window", "sunset", "walking path", "coffee morning"],
                      "#selfgrowth #lifelessons #mentalclarity #dailythoughts"),
    "relationships": (["sunset beach", "city lights", "autumn leaves", "starry sky"],
                      "#relationships #friendship #connection #lifequotes"),
    "discipline and habits": (["running track", "sunrise gym", "clock time", "road"],
                              "#discipline #habits #consistency #selfimprovement"),
    "money and mindset": (["city traffic", "skyscrapers", "stock city night", "rain city"],
                          "#moneymindset #financialfreedom #wealth #growthmindset"),
}

# Original lines (no famous quotes, so no attribution/copyright worries)
FALLBACK_QUOTES = {
    "inspiration": [
        "You don't need a perfect start. You need a start.",
        "Small steps still leave footprints. Keep walking.",
        "The version of you that you're waiting to become is built by what you do today.",
        "Doubt is loud, but action is louder. Move anyway.",
    ],
    "professional life": [
        "Your career is a long game. Stop panicking over one slow quarter.",
        "Be the person who makes the team calmer, not louder.",
        "Skills pay rent. Show up, learn something, repeat.",
        "A good reputation is built in the moments nobody is clapping.",
    ],
    "personal life": [
        "Rest is not a reward. It's part of the work.",
        "You're allowed to outgrow places that once felt like home.",
        "Peace is a decision you keep making, not a place you arrive at.",
        "Protect your quiet mornings. They shape the whole day.",
    ],
    "relationships": [
        "The right people never make you audition for their love.",
        "Real friends check in even when you seem fine.",
        "Be gentle with people. Everyone is carrying something you can't see.",
        "Distance shows who was reaching and who was just nearby.",
    ],
    "discipline and habits": [
        "Motivation starts the engine. Habits drive the car.",
        "You don't rise to your goals. You fall to your routine.",
        "Do it tired. Do it bored. Do it anyway.",
        "Consistency is boring until the results show up.",
    ],
    "money and mindset": [
        "Spend like your future self is watching, because they are.",
        "Income opens doors. Habits decide what you do inside.",
        "Wealth is mostly patience wearing a good disguise.",
        "Don't buy it to impress people who aren't even paying attention.",
    ],
}


def http_get_json(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_quote(category):
    """Try Gemini for a fresh quote; fall back to the built-in list."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        try:
            prompt = (
                f"Write ONE original, punchy quote about {category} for an Instagram Reel. "
                "Max 22 words, no author, no hashtags, no emojis, no quotation marks. "
                "Make it relatable and shareable. Output only the quote."
            )
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"gemini-2.0-flash:generateContent?key={key}")
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
            data = http_get_json(url, {"Content-Type": "application/json"}, body)
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
            if 8 <= len(text) <= 200:
                return text
        except Exception as exc:  # noqa: BLE001
            print(f"Gemini failed ({exc}); using built-in quote.")
    return random.choice(FALLBACK_QUOTES[category])


def download_background(terms):
    """Download a Pixabay video. Returns a Path, or None if unavailable (reason is printed)."""
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key:
        print("BACKGROUND: PIXABAY_API_KEY is empty or missing in this run -> gradient used. "
              "Check the secret name is exactly PIXABAY_API_KEY under Settings > Secrets > Actions.")
        return None
    queries = random.sample(terms, k=min(3, len(terms))) + ["nature", ""]
    for term in queries:
        try:
            q = urllib.parse.quote(term)
            url = f"https://pixabay.com/api/videos/?key={key}&q={q}&per_page=30&safesearch=true"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            hits = [h for h in data.get("hits", []) if 4 <= h.get("duration", 0) <= 60]
            print(f"BACKGROUND: search '{term}' -> {len(data.get('hits', []))} hits, {len(hits)} usable")
            if not hits:
                continue
            hit = random.choice(hits)
            vids = hit["videos"]
            for size in ("medium", "large", "small", "tiny"):
                link = (vids.get(size) or {}).get("url")
                if not link:
                    continue
                dest = TMP_DIR / "bg.mp4"
                req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
                    f.write(r.read())
                if dest.stat().st_size > 50_000:
                    print(f"BACKGROUND: using Pixabay video ({size}, {dest.stat().st_size / 1e6:.1f} MB)")
                    return dest
        except Exception as exc:  # noqa: BLE001
            print(f"BACKGROUND: search '{term}' failed: {exc}")
    print("BACKGROUND: all Pixabay attempts failed -> gradient used.")
    return None


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                try:
                    font.set_variation_by_name("Bold")  # variable-font builds only
                except Exception:  # noqa: BLE001
                    pass
                return font
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_to_width(draw, text, font, max_width):
    """Greedy word-wrap using real pixel widths (not character counts)."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(draw, text):
    """Largest font size where the wrapped text fits the safe box. Returns (font, lines, spacing)."""
    max_w = BOX_RIGHT - BOX_LEFT
    max_h = BOX_BOTTOM - BOX_TOP
    for size in range(MAX_FONT, MIN_FONT - 1, -2):
        font = load_font(size)
        lines = wrap_to_width(draw, text, font, max_w)
        spacing = int(size * 0.32)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        total_h = len(lines) * line_h + (len(lines) - 1) * spacing
        widest_ok = all(draw.textlength(l, font=font) <= max_w for l in lines)
        if total_h <= max_h and widest_ok and len(lines) <= 9:
            return font, lines, spacing, line_h
    font = load_font(MIN_FONT)  # last resort
    lines = wrap_to_width(draw, text, font, max_w)
    return font, lines, int(MIN_FONT * 0.32), font.getbbox("Ag")[3] - font.getbbox("Ag")[1]


def render_text_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font, lines, spacing, line_h = fit_text(draw, text)
    total_h = len(lines) * line_h + (len(lines) - 1) * spacing
    y = BOX_TOP + ((BOX_BOTTOM - BOX_TOP) - total_h) // 2  # vertically centred in the box
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (W - w) / 2
        # soft shadow for readability on any background
        draw.text((x + 4, y + 5), line, font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h + spacing
    # small handle near the bottom (above Instagram's caption area)
    small = load_font(40)
    hw = draw.textlength(HANDLE, font=small)
    draw.text(((W - hw) / 2, 1500), HANDLE, font=small, fill=(255, 255, 255, 200))
    img.save(path)
    print(f"Text fitted: {len(lines)} lines, font size {font.size}")


def reel_duration(text):
    words = len(text.split())
    return max(8, min(15, round(5 + words * 0.4)))


def build_video(bg, text_png, duration, out_path):
    fade_in = "format=rgba,fade=t=in:st=0.5:d=0.9:alpha=1"
    if bg:
        bg_input = ["-stream_loop", "-1", "-i", str(bg)]
        base = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps=30,eq=brightness=-0.18:saturation=1.05[bg]")
    else:
        bg_input = ["-f", "lavfi", "-i",
                    f"gradients=s={W}x{H}:c0=0x1f1c2c:c1=0x928dab:x0=0:y0=0:x1={W}:y1={H}"
                    f":speed=0.015:d={duration}"]
        base = "[0:v]fps=30,setsar=1[bg]"
    cmd = [
        "ffmpeg", "-y", *bg_input,
        "-loop", "1", "-i", str(text_png),
        "-filter_complex",
        f"{base};[1:v]{fade_in}[txt];[bg][txt]overlay=0:0:format=auto,format=yuv420p[v]",
        "-map", "[v]", "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-movflags", "+faststart", "-an", str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    category = random.choice(list(CATEGORIES))
    terms, tags = CATEGORIES[category]
    quote = pick_quote(category)
    print(f"Category: {category}\nQuote: {quote}")

    text_png = TMP_DIR / "text.png"
    render_text_png(quote, text_png)

    bg = download_background(terms)
    duration = reel_duration(quote)
    out_mp4 = OUT_DIR / "reel.mp4"
    build_video(bg, text_png, duration, out_mp4)

    stamp = int(time.time())
    meta = {
        "category": category,
        "quote": quote,
        "caption": f"{quote}\n\nSave this for later and follow {HANDLE} for daily reminders.\n\n{tags} #reels #quotes",
        "video_url": f"{REPO_RAW}/reels/out/reel.mp4?v={stamp}",
        "duration_seconds": duration,
        "generated_at": stamp,
    }
    (OUT_DIR / "reel.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Done:", out_mp4, f"({out_mp4.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("FFmpeg failed:", exc, file=sys.stderr)
        sys.exit(1)
