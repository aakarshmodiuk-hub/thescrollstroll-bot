import datetime
import json
import os
import random
import time
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

# If Gemini ever says "model not found", change this to a current model name
# from aistudio.google.com (for example gemini-3.5-flash-lite).
MODEL = "gemini-2.5-flash"

API_KEY = os.environ["GEMINI_API_KEY"]
REPO = os.environ.get("GITHUB_REPOSITORY", "USER/REPO")
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TODAY = datetime.date.today().isoformat()
HANDLE = "@TheScrollStroll"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (scrollstroll-bot)"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def trend_topics():
    feeds = [
        "https://trends.google.com/trending/rss?geo=GB",
        "https://trends.google.com/trending/rss?geo=US",
        "https://www.reddit.com/r/AskReddit/top/.rss?t=day",
        "https://www.reddit.com/r/memes/top/.rss?t=day",
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
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 1.0,
            },
        }
    ).encode()
    for attempt in range(4):
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
            result = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
            return result[0] if isinstance(result, list) else result
        except Exception as e:
            print("Gemini attempt failed:", e)
            time.sleep(10 * (attempt + 1))
    raise SystemExit("Gemini failed after several tries")


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


def render(text, path):
    W, H = 1080, 1350  # 4:5 portrait, takes more room in the feed
    palettes = [
        ("#111111", "#FFFFFF"),
        ("#FFD60A", "#111111"),
        ("#1E3A8A", "#FFFFFF"),
        ("#065F46", "#FFFFFF"),
        ("#BE185D", "#FFFFFF"),
    ]
    bg, fg = random.choice(palettes)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    margin = 90

    for size in range(88, 35, -4):
        font = ImageFont.truetype(FONT, size)
        lines = []
        for para in text.split("\n"):
            lines += wrap(para, font, draw, W - 2 * margin)
            lines.append("")
        lines = lines[:-1]
        line_h = int(size * 1.3)
        if len(lines) * line_h <= H - 2 * margin - 100:
            break

    y = (H - 100 - len(lines) * line_h) / 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, y), line, font=font, fill=fg)
        y += line_h

    small = ImageFont.truetype(FONT, 34)
    w = draw.textlength(HANDLE, font=small)
    draw.text(((W - w) / 2, H - 100), HANDLE, font=small, fill=fg)
    img.save(path, "JPEG", quality=95)


# ---------- main ----------
history = []
if os.path.exists("history.json"):
    history = json.load(open("history.json"))
recent = [h["topic"] for h in history[-20:]]

topics = trend_topics()
trend_text = "\n".join("- " + t for t in topics) or "- (no trend data today, use evergreen relatable themes)"

prompt = f"""You run TheScrollStroll, an Instagram page of relatable, funny, light-hearted memes for a broad young-adult audience.
Today's date: {TODAY}.

Trending right now:
{trend_text}

Recently used topics (do NOT repeat these): {recent}

Write ONE original meme that is relatable (everyday life, work, sleep, money, social media, group chats, procrastination, etc).
You may nod to a trend if it fits naturally, but the joke must make sense to someone who does not know the trend.
No politics, no tragedies, no hate, no insults to real people.

Rules for meme_text: max 140 characters, two short lines separated by a newline, in a format like "Me: ... / Also me: ..." or "Nobody: / Me: ...". No emojis in meme_text.

Return JSON with these keys:
topic (short string), meme_text (string), caption (1-2 sentences, up to 2 emojis allowed),
hashtags (list of 6 strings, no # symbol), score (integer 1-10, your honest rating of how funny and relatable it is)."""

best = None
for _ in range(3):
    result = ask_gemini(prompt)
    print("Attempt score:", result.get("score"), "|", result.get("meme_text"))
    if best is None or result["score"] > best["score"]:
        best = result
    if result["score"] >= 7:
        break
meme = best

os.makedirs("output", exist_ok=True)
image_name = f"{TODAY}.jpg"
render(meme["meme_text"], f"output/{image_name}")

caption = meme["caption"] + "\n\n" + " ".join("#" + h.lstrip("#") for h in meme["hashtags"])
payload = {
    "date": TODAY,
    "caption": caption,
    "image_url": f"https://raw.githubusercontent.com/{REPO}/main/output/{image_name}",
    "topic": meme["topic"],
}
with open("output/today.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

history.append({"date": TODAY, "topic": meme["topic"], "text": meme["meme_text"]})
with open("history.json", "w", encoding="utf-8") as f:
    json.dump(history[-60:], f, ensure_ascii=False, indent=2)

# tidy up: delete dated images older than 14 days
cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat() + ".jpg"
for name in os.listdir("output"):
    if name.endswith(".jpg") and name[0].isdigit() and name < cutoff:
        os.remove(os.path.join("output", name))

print("Done:", meme["meme_text"])
