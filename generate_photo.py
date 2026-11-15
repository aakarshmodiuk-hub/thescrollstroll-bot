import datetime
import io
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

# The script tries these in order and uses the first one that works.
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-2.5-flash-lite",
]

API_KEY = os.environ["GEMINI_API_KEY"]
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "USER/REPO")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TODAY = datetime.date.today().isoformat()
HANDLE = "@TheScrollStroll"
W, H = 1080, 1350  # 4:5 portrait


def get(url, headers=None):
    h = {"User-Agent": "Mozilla/5.0 (scrollstroll-bot)"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def trend_topics():
    feeds = [
        "https://trends.google.com/trending/rss?geo=GB",
        "https://trends.google.com/trending/rss?geo=US",
        "https://www.reddit.com/r/AskReddit/top/.rss?t=day",
    ]
    topics = []
    for url in feeds:
        try:
            root = ET.fromstring(get(url))
            titles = [
                e.text
                for e in root.iter()
                if e.tag.split("}")[-1] == "title" and e.text
            ][1:11]
            topics += titles
            print("OK:", url, len(titles), "items")
        except Exception as e:
            print("Feed failed (that's okay):", url, e)
    return topics


def ask_gemini(prompt):
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 1.0,
            },
        }
    ).encode()
    for model in MODELS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": API_KEY,
                    },
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
                result = json.loads(
                    data["candidates"][0]["content"]["parts"][0]["text"]
                )
                print("Used model:", model)
                return result[0] if isinstance(result, list) else result
            except urllib.error.HTTPError as e:
                print(model, "failed:", e.code, e.read()[:300])
                if e.code == 404:
                    break  # model name not valid, try the next one
                time.sleep(15)
            except Exception as e:
                print(model, "failed:", e)
                time.sleep(15)
    raise SystemExit("Gemini failed with every model")


def fetch_photo(queries, used_ids):
    """Tries each search in turn. Returns (PIL image, credit, photo id) or (None, None, None)."""
    if not PIXABAY_KEY:
        print("No PIXABAY_API_KEY set")
        return None, None, None
    for query in queries:
        if not query:
            continue
        try:
            url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
                {
                    "key": PIXABAY_KEY,
                    "q": query,
                    "image_type": "photo",
                    "orientation": "vertical",
                    "safesearch": "true",
                    "per_page": 20,
                }
            )
            data = json.loads(get(url))
            hits = [p for p in data.get("hits", []) if p["id"] not in used_ids]
            if not hits:
                print("No unused photos found for:", query)
                continue
            photo = random.choice(hits[:10])
            raw = get(photo["largeImageURL"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            credit = f"Image by {photo['user']} on Pixabay"
            print("Photo chosen:", photo["id"], "for query:", query)
            return img, credit, photo["id"]
        except Exception as e:
            print("Photo fetch failed for", query, ":", e)
    return None, None, None


def wrap(text, font, draw, max_w):
    lines, current = [], ""
    for word in text.split():
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def cover_crop(img, w, h):
    scale = max(w / img.width, h / img.height)
    new_size = (int(img.width * scale) + 1, int(img.height * scale) + 1)
    img = img.resize(new_size, Image.Resampling.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def render(text, path, photo=None):
    margin = 90
    if photo is not None:
        img = cover_crop(photo, W, H)
        img = Image.blend(img, Image.new("RGB", (W, H), "black"), 0.35)
        fg, stroke = "#FFFFFF", 5
        box_h = int(H * 0.45)  # text sits in the top part of the photo
    else:
        # fallback if no photo could be fetched: a plain colour text card
        palettes = [
            ("#111111", "#FFFFFF"),
            ("#FFD60A", "#111111"),
            ("#1E3A8A", "#FFFFFF"),
            ("#065F46", "#FFFFFF"),
            ("#BE185D", "#FFFFFF"),
        ]
        bg, fg = random.choice(palettes)
        img = Image.new("RGB", (W, H), bg)
        stroke = 0
        box_h = H - 2 * margin - 100

    draw = ImageDraw.Draw(img)

    for size in range(88, 35, -4):
        font = ImageFont.truetype(FONT, size)
        lines = []
        for para in text.split("\n"):
            lines += wrap(para, font, draw, W - 2 * margin)
            lines.append("")
        lines = lines[:-1]
        line_h = int(size * 1.3)
        if len(lines) * line_h <= box_h:
            break

    if photo is not None:
        y = margin
    else:
        y = (H - 100 - len(lines) * line_h) / 2

    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(
            ((W - w) / 2, y),
            line,
            font=font,
            fill=fg,
            stroke_width=stroke,
            stroke_fill="black",
        )
        y += line_h

    small = ImageFont.truetype(FONT, 34)
    w = draw.textlength(HANDLE, font=small)
    draw.text(
        ((W - w) / 2, H - 100),
        HANDLE,
        font=small,
        fill=fg,
        stroke_width=stroke // 2,
        stroke_fill="black",
    )
    img.save(path, "JPEG", quality=90)


# ---------- main ----------
NOW = datetime.datetime.now(datetime.timezone.utc)
STAMP = NOW.strftime("%Y-%m-%d-%H%M")

history = load_json("history_photo.json")
text_history = load_json("history.json")  # read only, never changed here
recent = [h.get("topic", "") for h in text_history[-30:] + history[-30:]]
recent_texts = [
    h.get("text", "").replace("\n", " / ") for h in text_history[-4:] + history[-4:]
]
used_ids = {h.get("photo_id") for h in history if h.get("photo_id")}

hour = NOW.hour
if 5 <= hour < 12:
    time_of_day = "morning"
elif 12 <= hour < 17:
    time_of_day = "afternoon"
elif 17 <= hour < 22:
    time_of_day = "evening"
else:
    time_of_day = "late night"

FORMATS = [
    "When ... (a one-line caption)",
    "Me after ... (a one-line caption)",
    "Nobody: / Me: ...",
    "POV: ...",
    "Expectation: ... / Reality: ...",
    "A one-line observation about modern life",
    "Things that hit different at this time of day",
]
chosen_format = random.choice(FORMATS)

topics = trend_topics()
trend_text = "\n".join("- " + t for t in topics) or "- (no trend data, use evergreen relatable themes)"

prompt = f"""You run TheScrollStroll, an Instagram page of relatable, funny, light-hearted memes for a broad young-adult audience.
Today's date: {TODAY}. It is currently {time_of_day} (UTC).

Trending right now:
{trend_text}

Recently used topics (do NOT repeat these): {recent}
Recent memes (do NOT write anything similar): {recent_texts}

Write ONE original PHOTO meme: a short caption that will be written over a stock photo, where the photo is part of the punchline.
It should be relatable (everyday life, work, sleep, money, social media, group chats, procrastination, food, friendships, pets, etc.).
You may nod to a trend if it fits naturally, but the joke must make sense to someone who does not know the trend.
Avoid overused cliches (going to bed early / 3 AM spirals, Mondays, coffee, adulting). Aim for a specific, surprising observation that makes people say "this is so me".
No politics, no tragedies, no hate, no insults to real people.

Use this caption format: {chosen_format}
Rules for meme_text: max 120 characters, short lines separated by a newline, no emojis in meme_text.

Photo rules: photo_query is a 2-4 word English search for a stock photo that makes the joke funnier
(examples: "sleepy cat", "messy desk", "empty fridge", "rainy window", "overflowing laundry basket").
photo_query_simple is a backup: ONE broad word (for example "cat", "desk", "rain").
Prefer animals, objects, food, places and nature. Avoid close-ups of people's faces. Never choose a photo that mocks a recognisable person.

Return JSON with these keys:
topic (short string), meme_text (string), caption (1-2 sentences, up to 2 emojis allowed),
hashtags (list of 6 strings, no # symbol), score (integer 1-10, your honest rating of how funny and relatable it is),
photo_query (string), photo_query_simple (string)."""

best = None
for _ in range(3):
    result = ask_gemini(prompt)
    print("Attempt score:", result.get("score"), "|", result.get("meme_text"))
    if best is None or result["score"] > best["score"]:
        best = result
    if result["score"] >= 7:
        break
meme = best

photo_img, credit, photo_id = fetch_photo(
    [meme.get("photo_query"), meme.get("photo_query_simple")], used_ids
)

os.makedirs("output", exist_ok=True)
image_name = f"photo-{STAMP}.jpg"
render(meme["meme_text"], f"output/{image_name}", photo_img)

caption = meme["caption"]
if credit:
    caption += f"\n\n📷 {credit}"
caption += "\n\n" + " ".join("#" + h.lstrip("#") for h in meme["hashtags"])

payload = {
    "date": TODAY,
    "epoch": int(NOW.timestamp()),
    "generated_at": NOW.isoformat(),
    "caption": caption,
    "image_url": f"https://raw.githubusercontent.com/{REPO}/main/output/{image_name}",
    "topic": meme["topic"],
}
with open("output/photo_today.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

history.append(
    {
        "date": TODAY,
        "topic": meme["topic"],
        "text": meme["meme_text"],
        "type": "photo" if photo_img is not None else "text",
        "photo_id": photo_id,
    }
)
with open("history_photo.json", "w", encoding="utf-8") as f:
    json.dump(history[-200:], f, ensure_ascii=False, indent=2)

# tidy up: delete photo-lane images older than 14 days
cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
for name in os.listdir("output"):
    if name.startswith("photo-") and name.endswith(".jpg") and name[6:16] < cutoff:
        os.remove(os.path.join("output", name))

print("Done:", meme["meme_text"])
