"""TheScrollStroll - Reel lane (quotes on a looping video background).

Makes a vertical (1080x1920) Reel with an auto-fitted quote and writes:
  reels/out/reel.mp4   the video
  reels/out/reel.json  caption + hashtags + video url (read by Make)

Quote, caption hook, hashtags and background search word are all written TOGETHER
for the same idea, so they always match each other. Without Gemini the built-in
quotes + that category's hashtags are used (still matched).

Secrets (optional - the script still works with none):
  PIXABAY_API_KEY  -> real video backgrounds
  GEMINI_API_KEY   -> fresh AI-written quotes, captions and hashtags
"""
import json
import os
import random
import re
import subprocess
import sys
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

# Text stays inside this safe box (Instagram's buttons cover the edges)
BOX_LEFT, BOX_RIGHT = 90, W - 90
BOX_TOP, BOX_BOTTOM = 420, 1380
MAX_FONT, MIN_FONT = 112, 52

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/montserrat/Montserrat[wght].ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

GEMINI_MODELS = ["gemini-flash-latest", "gemini-3.8-flash"]
MAX_HASHTAGS = 10          # Instagram allows 30; fewer, relevant ones work better
MAX_CAPTION_CHARS = 2000   # Instagram limit is 2200

# category -> (Pixabay search words, core hashtags that always fit the category)
CATEGORIES = {
    "inspiration": (["sunrise", "mountain clouds", "ocean waves", "forest light"],
                    ["#motivation", "#inspiration", "#mindset", "#growth", "#positivethinking"]),
    "professional life": (["city skyline", "office window", "city night", "laptop work"],
                          ["#careergrowth", "#worklife", "#leadership", "#success", "#careeradvice"]),
    "personal life": (["rain window", "sunset", "walking path", "coffee morning"],
                      ["#selfgrowth", "#lifelessons", "#mentalclarity", "#selfcare", "#innerpeace"]),
    "relationships": (["sunset beach", "city lights", "autumn leaves", "starry sky"],
                      ["#relationships", "#friendship", "#connection", "#lifequotes", "#kindness"]),
    "discipline and habits": (["running track", "sunrise gym", "clock time", "road"],
                              ["#discipline", "#habits", "#consistency", "#selfimprovement", "#focus"]),
    "money and mindset": (["city traffic", "skyscrapers", "rain city", "city night"],
                          ["#moneymindset", "#financialfreedom", "#wealth", "#growthmindset", "#abundance"]),
}
ALWAYS_TAGS = ["#quotes", "#reels"]
# spammy tags that hurt reach and do not describe the content
BANNED_TAGS = {"#fyp", "#foryou", "#foryoupage", "#viral", "#explore", "#trending", "#follow",
               "#followme", "#like4like", "#instagood", "#love", "#instagram"}

CTAS = [
    "Save this for later and follow {h} for daily reminders.",
    "Send this to someone who needs it today. Follow {h} for more.",
    "Read it twice. Then follow {h} for daily reminders.",
    "Tag a friend who needs this. More daily on {h}.",
]

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


# ---------------------------------------------------------------- content ----
def clean_tag(tag):
    """'#Self Growth!' -> '#selfgrowth' (letters/digits only, lowercase, 3-30 chars) or None."""
    body = re.sub(r"[^a-z0-9]", "", str(tag).lower().lstrip("#"))
    return f"#{body}" if 3 <= len(body) <= 30 else None


def clean_search_word(text):
    words = re.sub(r"[^a-zA-Z ]", " ", str(text)).split()
    return " ".join(words[:2]).lower() if words else None


def ask_gemini(category):
    """One call returns quote + hook + hashtags + visual together, so they match each other."""
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        print("CONTENT: GEMINI_API_KEY missing -> built-in quote.")
        return None
    prompt = (
        f"You write Instagram Reel content for the page {HANDLE}. Topic: {category}.\n"
        "Return ONLY a JSON object with these keys:\n"
        '  "quote": one original, punchy, relatable quote, max 22 words, no author, '
        "no emojis, no quotation marks;\n"
        '  "hook": one short caption line (max 14 words) that reacts to THIS quote, '
        "no hashtags;\n"
        '  "hashtags": 4 to 6 lowercase hashtags specific to THIS quote\'s idea '
        "(not generic spam like #fyp or #viral);\n"
        '  "visual": 1 or 2 plain words describing a calm background video that fits the '
        'mood of the quote (for example "sunrise", "city night", "ocean").'
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    for model in GEMINI_MODELS:
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            data = http_get_json(url, {"Content-Type": "application/json"}, body)
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            obj = json.loads(text)
            quote = str(obj.get("quote", "")).strip().strip('"')
            if not 8 <= len(quote) <= 200:
                print(f"CONTENT: {model} quote unusable, trying next.")
                continue
            hook = str(obj.get("hook", "")).strip()
            hook = re.sub(r"#\w+", "", hook).strip()
            tags = [t for t in (clean_tag(x) for x in obj.get("hashtags", [])) if t and t not in BANNED_TAGS]
            print(f"CONTENT: written by Gemini ({model})")
            return {
                "quote": quote,
                "hook": hook if 3 <= len(hook) <= 140 else "",
                "tags": tags,
                "visual": clean_search_word(obj.get("visual", "")),
            }
        except Exception as exc:  # noqa: BLE001
            print(f"CONTENT: {model} failed ({exc}), trying next.")
    print("CONTENT: Gemini unavailable -> built-in quote.")
    return None


def build_caption(quote, hook, extra_tags, category):
    """Quote + hook + call to action + hashtags that all belong together."""
    core = CATEGORIES[category][1]
    tags = []
    for t in extra_tags[:4] + core[:4] + ALWAYS_TAGS:   # quote-specific first, then category
        if t not in tags:
            tags.append(t)
    tags = tags[:MAX_HASHTAGS]
    cta = random.choice(CTAS).format(h=HANDLE)
    parts = [quote]
    if hook:
        parts.append(hook)
    parts.append(cta)
    parts.append(" ".join(tags))
    caption = "\n\n".join(parts)
    if len(caption) > MAX_CAPTION_CHARS:
        caption = caption[:MAX_CAPTION_CHARS].rsplit(" ", 1)[0]
    return caption, tags


# ------------------------------------------------------------- background ----
def download_background(search_words):
    """Download a Pixabay video. Returns a Path or None (the reason is printed)."""
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key:
        print("BACKGROUND: PIXABAY_API_KEY empty or missing -> gradient used.")
        return None
    for term in search_words + ["nature", ""]:
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
            vids = random.choice(hits)["videos"]
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


# ------------------------------------------------------------------- text ----
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
    """Largest font size where the wrapped text fits the safe box."""
    max_w, max_h = BOX_RIGHT - BOX_LEFT, BOX_BOTTOM - BOX_TOP
    for size in range(MAX_FONT, MIN_FONT - 1, -2):
        font = load_font(size)
        lines = wrap_to_width(draw, text, font, max_w)
        spacing = int(size * 0.32)
        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        total_h = len(lines) * line_h + (len(lines) - 1) * spacing
        if total_h <= max_h and all(draw.textlength(l, font=font) <= max_w for l in lines) and len(lines) <= 9:
            return font, lines, spacing, line_h
    font = load_font(MIN_FONT)
    lines = wrap_to_width(draw, text, font, max_w)
    return font, lines, int(MIN_FONT * 0.32), font.getbbox("Ag")[3] - font.getbbox("Ag")[1]


def render_text_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font, lines, spacing, line_h = fit_text(draw, text)
    total_h = len(lines) * line_h + (len(lines) - 1) * spacing
    y = BOX_TOP + ((BOX_BOTTOM - BOX_TOP) - total_h) // 2
    for line in lines:
        x = (W - draw.textlength(line, font=font)) / 2
        draw.text((x + 4, y + 5), line, font=font, fill=(0, 0, 0, 170))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h + spacing
    small = load_font(40)
    hw = draw.textlength(HANDLE, font=small)
    draw.text(((W - hw) / 2, 1500), HANDLE, font=small, fill=(255, 255, 255, 200))
    img.save(path)
    print(f"TEXT: fitted {len(lines)} lines, font size {font.size}")


def reel_duration(text):
    return max(8, min(15, round(5 + len(text.split()) * 0.4)))


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
        "ffmpeg", "-y", "-loglevel", "error", *bg_input,
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
    search_words, _core = CATEGORIES[category]
    content = ask_gemini(category)
    if content:
        quote, hook, extra_tags, visual = content["quote"], content["hook"], content["tags"], content["visual"]
    else:
        quote, hook, extra_tags, visual = random.choice(FALLBACK_QUOTES[category]), "", [], None
    print(f"CATEGORY: {category}\nQUOTE: {quote}")

    caption, tags = build_caption(quote, hook, extra_tags, category)
    print("TAGS:", " ".join(tags))

    text_png = TMP_DIR / "text.png"
    render_text_png(quote, text_png)

    terms = ([visual] if visual else []) + random.sample(search_words, k=min(3, len(search_words)))
    bg = download_background(terms)
    duration = reel_duration(quote)
    out_mp4 = OUT_DIR / "reel.mp4"
    build_video(bg, text_png, duration, out_mp4)

    stamp = int(time.time())
    meta = {
        "category": category,
        "quote": quote,
        "caption": caption,
        "hashtags": tags,
        "video_url": f"{REPO_RAW}/reels/out/reel.mp4?v={stamp}",
        "duration_seconds": duration,
        "generated_at": stamp,
    }
    (OUT_DIR / "reel.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("DONE:", out_mp4, f"({out_mp4.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print("FFmpeg failed:", exc, file=sys.stderr)
        sys.exit(1)
