"""
TheScrollStroll meme bot: trends -> Gemini idea -> quality gate -> Pillow render -> Instagram.
Runs from GitHub Actions. Free stack, no watermark.
"""
import datetime
import glob
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ---------- config ----------
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")  # check AI Studio for current free models
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
PAUSED = os.environ.get("PAUSED", "").lower() == "true"  # kill-switch (repo variable PAUSED=true)

MIN_SCORE = 7           # quality gate (1-10)
MAX_ATTEMPTS = 4        # tries per run before skipping
KEEP_IMAGES = 20        # old images pruned from repo
SIZE = 1080
GRAPH = "https://graph.facebook.com/v21.0"
UA = {"User-Agent": "TheScrollStrollBot/1.0 (meme page automation)"}

# Topics we never touch. Extend freely.
BLOCK = re.compile(
    r"\b(dead|death|died|dies|killed|killing|shooting|shooter|massacre|suicide|murder|rape|assault|"
    r"abuse|terror|attack|bomb|war|genocide|hostage|crash|victim|funeral|cancer|tragedy|"
    r"trump|biden|harris|election|abortion|nazi|hamas|israel|gaza|ukraine|putin|"
    r"racist|slur|lawsuit|arrested|charged|trial)\b",
    re.I,
)

FONT_CANDIDATES = [
    "fonts/font.ttf",  # drop an Anton/Impact-style .ttf here for the classic meme look
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT = next((f for f in FONT_CANDIDATES if os.path.exists(f)), None)
if FONT is None:
    sys.exit("No font found. Add fonts/font.ttf or install fonts-dejavu-core.")


# ---------- state ----------
def load_state():
    try:
        with open("state.json") as f:
            return json.load(f)
    except Exception:
        return {"topics": []}


def save_state(state):
    state["topics"] = state["topics"][-300:]
    with open("state.json", "w") as f:
        json.dump(state, f, indent=1)


# ---------- trends ----------
def google_trends():
    try:
        r = requests.get("https://trends.google.com/trending/rss?geo=US", headers=UA, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [i.findtext("title") for i in root.iter("item") if i.findtext("title")]
    except Exception as e:
        print("google trends failed:", e)
        return []


def wikipedia_trends():
    try:
        d = datetime.date.today() - datetime.timedelta(days=2)
        url = (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
            f"en.wikipedia/all-access/{d.year}/{d.month:02d}/{d.day:02d}"
        )
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        out = []
        for a in r.json()["items"][0]["articles"]:
            t = a["article"].replace("_", " ")
            if ":" in t or t in ("Main Page", "-"):
                continue
            out.append(t)
        return out[:30]
    except Exception as e:
        print("wikipedia trends failed:", e)
        return []


def get_trends(state):
    seen = {t.lower() for t in state["topics"]}
    items, out = google_trends() + wikipedia_trends(), []
    for t in items:
        if t.lower() in seen or BLOCK.search(t) or t in out:
            continue
        out.append(t)
    return out[:25]


# ---------- gemini ----------
def gemini_json(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }
    last = None
    for attempt in range(4):
        r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=90)
        if r.status_code in (429, 500, 503):
            last = r.text[:200]
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        return json.loads(text)
    raise RuntimeError(f"Gemini failed: {last}")


def template_files():
    return sorted(
        os.path.basename(p)
        for p in glob.glob("templates/*")
        if p.lower().endswith((".jpg", ".jpeg", ".png"))
    )


def generate_meme(trends, state, templates):
    tmpl_line = (
        "Available image templates (classic top/bottom caption photos): "
        + ", ".join(templates)
        + '. Set "format" to one of these filenames, or "text_card".'
        if templates
        else 'Set "format" to "text_card".'
    )
    prompt = f"""You write memes for an Instagram page called TheScrollStroll: relatable, internet-native, witty humor.
Trending topics right now: {json.dumps(trends[:15])}
Recently used topics (do NOT repeat): {json.dumps(state['topics'][-30:])}

Pick ONE topic and write ONE meme. Rules:
- Make it relatable to everyday life (scrolling, work, sleep, money, friends, phones); the trend can be a light hook.
- top_text = setup, bottom_text = punchline. Each max 12 words. No hashtags in them.
- No tragedy, politics, religion, tragedies, real-person insults, or sensitive topics. Never name a private person.
- Do not claim facts about news you are unsure of.
{tmpl_line}

Return JSON only:
{{"topic": str, "format": str, "top_text": str, "bottom_text": str, "caption": str, "hashtags": [5-8 strings without #]}}"""
    return gemini_json(prompt)


def judge(meme):
    prompt = f"""You are a strict editor for a general-audience meme page. Review this meme:
{json.dumps(meme)}
Score humor and clarity 1-10 (be harsh; 7 = would genuinely get shares). Mark safe=false if it is offensive,
touches tragedy, politics, religion, sexual content, a real identifiable person, or a factual claim that may be false.
Return JSON only: {{"score": int, "safe": bool, "reason": str}}"""
    return gemini_json(prompt)


# ---------- rendering ----------
def layout(draw, text, size, max_w):
    font = ImageFont.truetype(FONT, size)
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return font, lines


def fit(draw, text, max_w, max_h, start=110, minimum=34):
    for size in range(start, minimum - 1, -4):
        font, lines = layout(draw, text, size, max_w)
        lh = int(size * 1.18)
        if len(lines) * lh <= max_h:
            break
    return font, lines, lh


def draw_block(draw, text, y0, box_h, align, fill, stroke=None):
    pad = 50
    font, lines, lh = fit(draw, text, SIZE - 2 * pad, box_h)
    total = len(lines) * lh
    y = {"top": y0, "bottom": y0 + box_h - total}.get(align, y0 + (box_h - total) // 2)
    for line in lines:
        w = draw.textlength(line, font=font)
        kw = dict(stroke_width=max(3, font.size // 14), stroke_fill=stroke) if stroke else {}
        draw.text(((SIZE - w) / 2, y), line, font=font, fill=fill, **kw)
        y += lh


def render(meme, path):
    fmt = meme.get("format", "text_card")
    top, bottom = meme["top_text"].strip(), meme["bottom_text"].strip()
    tpath = os.path.join("templates", fmt)
    if fmt != "text_card" and os.path.exists(tpath):
        img = ImageOps.fit(Image.open(tpath).convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
        d = ImageDraw.Draw(img)
        draw_block(d, top.upper(), 15, 300, "top", "white", "black")
        draw_block(d, bottom.upper(), SIZE - 315, 300, "bottom", "white", "black")
    else:
        palettes = [((18, 18, 24), (255, 214, 10)), ((250, 247, 240), (200, 30, 60)),
                    ((12, 40, 70), (120, 220, 255)), ((30, 10, 50), (255, 120, 200))]
        bg, accent = random.choice(palettes)
        light = sum(bg) > 400
        main = (20, 20, 20) if light else (255, 255, 255)
        img = Image.new("RGB", (SIZE, SIZE), bg)
        d = ImageDraw.Draw(img)
        draw_block(d, top, 70, 420, "center", main)
        d.rectangle([SIZE // 2 - 80, SIZE // 2 - 3, SIZE // 2 + 80, SIZE // 2 + 3], fill=accent)
        draw_block(d, bottom, 520, 420, "center", accent)
    img.save(path, "JPEG", quality=92)


# ---------- git + instagram ----------
def sh(*args):
    subprocess.run(args, check=True)


def prune_images():
    files = sorted(glob.glob("images/*.jpg"), key=os.path.getmtime)
    for old in files[:-KEEP_IMAGES]:
        os.remove(old)


def commit_and_push(msg):
    sh("git", "config", "user.name", "meme-bot")
    sh("git", "config", "user.email", "meme-bot@users.noreply.github.com")
    sh("git", "add", "-A", "images", "state.json")
    sh("git", "commit", "-m", msg)
    sh("git", "push")


def wait_until_live(url, tries=12):
    for _ in range(tries):
        if requests.head(url, timeout=20).status_code == 200:
            return
        time.sleep(5)
    raise RuntimeError(f"Image never became reachable: {url}")


def ig_post(image_url, caption):
    r = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": IG_TOKEN},
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"IG container failed: {r.text}")
    cid = r.json()["id"]
    for _ in range(12):
        s = requests.get(
            f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": IG_TOKEN}, timeout=30
        ).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
        time.sleep(5)
    r = requests.post(
        f"{GRAPH}/{IG_USER_ID}/media_publish",
        data={"creation_id": cid, "access_token": IG_TOKEN},
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"IG publish failed: {r.text}")
    print("Published:", r.json())


# ---------- main ----------
def main():
    if PAUSED:
        print("PAUSED=true, skipping.")
        return
    state = load_state()
    trends = get_trends(state)
    if not trends:
        sys.exit("No usable trends found.")
    templates = template_files()

    meme = None
    for i in range(MAX_ATTEMPTS):
        try:
            cand = generate_meme(trends, state, templates)
            if BLOCK.search(json.dumps(cand)):
                print("blocked by keyword filter")
                continue
            v = judge(cand)
            print(f"attempt {i+1}: score={v.get('score')} safe={v.get('safe')} | {cand.get('top_text')} / {cand.get('bottom_text')}")
            if v.get("safe") and v.get("score", 0) >= MIN_SCORE:
                meme = cand
                break
        except Exception as e:
            print("attempt failed:", e)
    if not meme:
        print("Nothing passed the quality gate; skipping this run.")
        return

    name = hashlib.md5(f"{time.time()}{meme['topic']}".encode()).hexdigest()[:10] + ".jpg"
    os.makedirs("images", exist_ok=True)
    path = f"images/{name}"
    render(meme, path)

    tags = " ".join("#" + re.sub(r"\W", "", h) for h in meme.get("hashtags", [])[:8])
    caption = f"{meme['caption'].strip()}\n\n{tags}".strip()
    state["topics"].append(meme["topic"])
    save_state(state)

    if DRY_RUN:
        print("DRY RUN. Image saved to", path, "\nCaption:\n", caption)
        return

    prune_images()
    commit_and_push(f"meme {name}")
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}"
    wait_until_live(url)
    ig_post(url, caption)


if __name__ == "__main__":
    main()
