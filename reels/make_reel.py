"""TheScrollStroll - Reel lane (quotes on a looping video background).

Makes a vertical (1080x1920) Reel and writes reels/out/reel.mp4 and reel.json.
Optional secrets: PIXABAY_API_KEY and GEMINI_API_KEY.
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
from audio_mixer import mix_audio

W, H = 1080, 1920
OUT_DIR = Path("reels/out")
TMP_DIR = Path("reels/tmp")
HANDLE = "@TheScrollStroll"
REPO_RAW = os.environ.get(
    "REPO_RAW_BASE",
    "https://raw.githubusercontent.com/aakarshmodiuk-hub/thescrollstroll-bot/main",
)
BOX_LEFT, BOX_RIGHT = 90, W - 90
BOX_TOP, BOX_BOTTOM = 420, 1380
MAX_FONT, MIN_FONT = 112, 52
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/ofl/montserrat/Montserrat[wght].ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
MAX_HASHTAGS = 6
MAX_CAPTION_CHARS = 2000
AUDIO_TAGS = [
    "lofi-chill", "late-night-ambient", "quirky-upbeat", "soft-piano",
    "rain-focus", "warm-acoustic", "peaceful-horizon",
]
AUDIO_TAG_FALLBACK = {
    "inspiration": "peaceful-horizon",
    "professional life": "rain-focus",
    "personal life": "soft-piano",
    "relationships": "warm-acoustic",
    "discipline and habits": "lofi-chill",
    "money and mindset": "late-night-ambient",
}
CATEGORIES = {
    "inspiration": (["sunrise", "mountain clouds", "ocean waves", "forest light"],
                    ["#selfgrowth", "#innerpeace", "#mindset", "#growth", "#lifelessons"]),
    "professional life": (["city skyline", "office window", "city night", "laptop work"],
                          ["#worklife", "#burnoutrecovery", "#careeradvice", "#mentalclarity", "#workbalance"]),
    "personal life": (["rain window", "sunset", "walking path", "coffee morning"],
                      ["#selfgrowth", "#lifelessons", "#mentalclarity", "#selfcare", "#innerpeace"]),
    "relationships": (["sunset beach", "city lights", "autumn leaves", "starry sky"],
                      ["#relationships", "#friendship", "#connection", "#selfrespect", "#emotionalwellbeing"]),
    "discipline and habits": (["running track", "sunrise gym", "clock time", "road"],
                              ["#discipline", "#habits", "#consistency", "#selfimprovement", "#focus"]),
    "money and mindset": (["city traffic", "skyscrapers", "rain city", "city night"],
                          ["#moneymindset", "#financialfreedom", "#wealth", "#growthmindset", "#moneyhabits"]),
}
ALWAYS_TAGS = ["#quotes", "#reels"]
BANNED_TAGS = {"#fyp", "#foryou", "#foryoupage", "#viral", "#explore", "#trending", "#follow",
               "#followme", "#like4like", "#instagood", "#love", "#instagram", "#motivation"}
CTAS = [
    "Save this for later and follow {h} for daily reminders.",
    "Send this to someone who needs it today. Follow {h} for more.",
    "Read it twice. Then follow {h} for daily reminders.",
    "Tag a friend who needs this. More daily on {h}.",
]
FALLBACK_QUOTES = {
    "inspiration": [
        "you don't need a perfect start. you need a start.",
        "small steps still leave footprints. keep walking.",
        "the version of you that you're waiting to become is built by what you do today.",
        "doubt is loud, but action is louder. move anyway.",
    ],
    "professional life": [
        "your career is a long game. stop panicking over one slow quarter.",
        "be the person who makes the team calmer, not louder.",
        "skills pay rent. show up, learn something, repeat.",
        "a good reputation is built in the moments nobody is clapping.",
    ],
    "personal life": [
        "rest is not a reward. it's part of the work.",
        "you're allowed to outgrow places that once felt like home.",
        "peace is a decision you keep making, not a place you arrive at.",
        "protect your quiet mornings. they shape the whole day.",
    ],
    "relationships": [
        "the right people never make you audition for their love.",
        "real friends check in even when you seem fine.",
        "be gentle with people. everyone is carrying something you can't see.",
        "distance shows who was reaching and who was just nearby.",
    ],
    "discipline and habits": [
        "motivation starts the engine. habits drive the car.",
        "you don't rise to your goals. you fall to your routine.",
        "do it tired. do it bored. do it anyway.",
        "consistency is boring until the results show up.",
    ],
    "money and mindset": [
        "spend like your future self is watching, because they are.",
        "income opens doors. habits decide what you do inside.",
        "wealth is mostly patience wearing a good disguise.",
        "don't buy it to impress people who aren't even paying attention.",
    ],
}


def http_get_json(url, headers=None, data=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def clean_tag(tag):
    body = re.sub(r"[^a-z0-9]", "", str(tag).lower().lstrip("#"))
    return f"#{body}" if 3 <= len(body) <= 30 else None


def clean_search_word(text):
    words = re.sub(r"[^a-zA-Z ]", " ", str(text)).split()
    return " ".join(words[:2]).lower() if words else None


def call_with_retry(url, body, attempts=2, timeout=60):
    import urllib.error
    last = None
    for n in range(1, attempts + 1):
        try:
            return http_get_json(url, {"Content-Type": "application/json"}, body, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except Exception as exc:
            last = exc
        print(f"CONTENT: attempt {n}/{attempts} failed ({last})")
        time.sleep(3)
    raise last


def ask_gemini(category):
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        print("CONTENT: GEMINI_API_KEY missing -> built-in quote.")
        return None
    prompt = (
        "You write one original Instagram Reel quote for @TheScrollStroll.\n"
        "The account is for quietly overwhelmed achievers: smart, self-aware people who want to improve their life without becoming loud, performative, or obsessed with productivity.\n"
        "Write like a calm, perceptive friend: grounded, emotionally intelligent, lightly witty, and specific. Avoid generic self-help language and motivational-poster energy.\n\n"
        f"Topic: {category}.\n\n"
        "Before writing, silently choose ONE distinct creative angle from this list:\n"
        "- a small everyday truth\n"
        "- a gentle reality check\n"
        "- a permission slip\n"
        "- a quiet boundary\n"
        "- a reframed habit\n"
        "- an emotionally honest observation\n"
        "- a hopeful but realistic thought\n"
        "- a dry, relatable insight\n\n"
        "Do not mention the angle. Make the quote feel fresh, human, and specific rather than like a recycled motivational quote.\n\n"
        "Rules:\n"
        "- Do not use these phrases: 'rise and grind', 'hustle harder', 'good vibes only', 'you got this', 'believe in yourself', 'never give up', or 'your future self'.\n"
        "- No emojis, no author attribution, no quotation marks, no hashtags in the quote.\n"
        "- Prefer lowercase except for 'I' and proper nouns.\n"
        "- Make the quote feel readable and punchy on a vertical Reel.\n\n"
        "Return ONLY a valid JSON object with these exact keys:\n\n"
        '"quote": one original quote, maximum 22 words, that creates a relatable smirk, quiet motivation, or a deep breath of peace;\n\n'
        '"hook": one short conversational caption line, maximum 14 words, that reacts to or deepens this exact quote with warmth, wit, or gentle reflection. No hashtags;\n\n'
        '"hashtags": 4 to 6 lowercase hashtags specific to this quote\'s exact theme and mood. Do not use generic spam tags such as #fyp, #viral, or #motivation;\n\n'
        '"visual": 1 or 2 plain words describing a calm, aesthetic Pixabay background video that fits the mood, for example "sunrise ocean", "rain window", "city night", "misty mountains", or "coffee steam";\n\n'
        '"audio_tag": choose ONE exact tag from this list that best matches the quote\'s mood: ["lofi-chill", "late-night-ambient", "quirky-upbeat", "soft-piano", "rain-focus", "warm-acoustic", "peaceful-horizon"].'
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    for model in GEMINI_MODELS:
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            data = call_with_retry(url, body)
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
            audio_tag = str(obj.get("audio_tag", "")).strip().lower()
            if audio_tag not in AUDIO_TAGS:
                audio_tag = AUDIO_TAG_FALLBACK[category]
            print(f"CONTENT: written by Gemini ({model})")
            return {
                "quote": quote,
                "hook": hook if 3 <= len(hook) <= 140 else "",
                "tags": tags,
                "visual": clean_search_word(obj.get("visual", "")),
                "audio_tag": audio_tag,
            }
        except Exception as exc:
            print(f"CONTENT: {model} failed ({exc}), trying next.")
    print("CONTENT: Gemini unavailable -> built-in quote.")
    return None


def build_caption(quote, hook, extra_tags, category):
    core = CATEGORIES[category][1]
    tags = []
    for t in extra_tags[:MAX_HASHTAGS] + core + ALWAYS_TAGS:
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


def download_background(search_words):
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
        except Exception as exc:
            print(f"BACKGROUND: search '{term}' failed: {exc}")
    print("BACKGROUND: all Pixabay attempts failed -> gradient used.")
    return None


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                try:
                    font.set_variation_by_name("Bold")
                except Exception:
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
        quote = content["quote"]
        hook = content["hook"]
        extra_tags = content["tags"]
        visual = content["visual"]
        audio_tag = content["audio_tag"]
    else:
        quote = random.choice(FALLBACK_QUOTES[category])
        hook = ""
        extra_tags = []
        visual = None
        audio_tag = AUDIO_TAG_FALLBACK[category]
    print(f"CATEGORY: {category}\nQUOTE: {quote}")
    print(f"AUDIO TAG: {audio_tag}")
    caption, tags = build_caption(quote, hook, extra_tags, category)
    print("TAGS:", " ".join(tags))
    text_png = TMP_DIR / "text.png"
    render_text_png(quote, text_png)
    terms = ([visual] if visual else []) + random.sample(search_words, k=min(3, len(search_words)))
    bg = download_background(terms)
    duration = reel_duration(quote)
    out_mp4 = OUT_DIR / "reel.mp4"
    build_video(bg, text_png, duration, out_mp4)
    audio_used = mix_audio(out_mp4, audio_tag, duration)
    stamp = int(time.time())
    meta = {
        "category": category,
        "quote": quote,
        "caption": caption,
        "hashtags": tags,
        "audio_tag": audio_tag,
        "audio_used": bool(audio_used),
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
